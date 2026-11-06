"""Checks of uploaded files (type, size, checksum) and what can be read from them (kind, PDF author). The files
themselves are stored in Supabase Storage (files.py), everything else in the database (app/db).
"""

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import BinaryIO

import pymupdf

from app.core.limits import LIMITS
from app.core.schemas import SourceKind

ALLOWED_EXTENSIONS = {".pdf"}  # widen when other formats get an ingestion path (EPUB, DOCX, video, ...)
MAX_UPLOAD_BYTES = LIMITS.per_user.max_upload_mb * 1024 * 1024  # limits.toml
CHUNK_BYTES = 1024 * 1024  # write in 1 MB pieces, never the whole file in memory

# File signatures ("magic bytes") the content must start with, per extension.
SIGNATURES = {".pdf": b"%PDF-"}


class UploadError(Exception):
    """Raised when an upload is rejected; carries the HTTP status code the API should return.

    Keeps this module independent of FastAPI: the endpoint catches it and converts it into an
    HTTPException (see server.upload_source).

    Args:
        status_code: HTTP status to report, e.g. 400 (empty), 413 (too large), 415 (wrong type).
        detail: Human-readable error message shown to the user.
    """

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def safe_filename(name: str) -> str:
    """Drop any directory part and characters that are unsafe in file names.

    Protects against path traversal ("../../etc/passwd") and names the file system cannot store.
    Works in three steps: keep only the part after the last "/" or "\\", replace every character
    other than letters, digits, "_", ".", "-", " ", "(" and ")" with "_", then strip leading and
    trailing spaces/dots and cut the name to 150 characters.

    Args:
        name: File name as sent by the client (may contain a path or be empty).

    Returns:
        A safe file name; "upload" if nothing usable is left.
    """
    name = re.split(r"[\\/]", name)[-1]
    name = re.sub(r"[^\w.\- ()]", "_", name).strip(" .")
    return name[:150] or "upload"


def save_upload(stream: BinaryIO, filename: str) -> tuple[Path, int, str]:
    """Validate an upload and stream it into a temporary file. Returns (path, size, SHA-256); the caller deletes the
    file (it goes on to Storage). Leaves nothing behind on failure.

    Checks the extension first, then copies the stream in CHUNK_BYTES pieces so large files never sit in memory as
    a whole. While copying it checks that the first bytes match the expected file signature and that the total size
    stays under MAX_UPLOAD_BYTES, and computes the content's SHA-256 checksum in the same pass (for the duplicate
    check). On any error (including client disconnects) the temporary file is removed before the exception is
    re-raised.

    Args:
        stream: Readable binary file object with the upload content (e.g. UploadFile.file).
        filename: Already sanitized file name (see safe_filename); its extension decides the type.

    Returns:
        Tuple of the temporary file's path, its size in bytes and its SHA-256 checksum (hex).

    Raises:
        UploadError: 415 for an unsupported extension or wrong content signature,
            413 when the file exceeds MAX_UPLOAD_BYTES, 400 when the file is empty.
    """
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise UploadError(415, f"Unsupported file type '{ext or 'none'}'. Allowed: {allowed}")

    handle, name = tempfile.mkstemp(prefix="upload-", suffix=ext)
    target = Path(name)
    size = 0
    digest = hashlib.sha256()
    try:
        with os.fdopen(handle, "wb") as out:
            while chunk := stream.read(CHUNK_BYTES):
                if size == 0 and ext in SIGNATURES and not chunk.startswith(SIGNATURES[ext]):
                    raise UploadError(415, f"The file content is not a valid {ext[1:].upper()}")
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise UploadError(413, f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
                out.write(chunk)
                digest.update(chunk)
        if size == 0:
            raise UploadError(400, "File is empty")
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target, size, digest.hexdigest()


def detect_kind(filename: str) -> SourceKind:
    """Guess the source kind from the file extension (case-insensitive).

    Args:
        filename: File name including its extension.

    Returns:
        "video", "audio" or "text" for known media/text extensions, otherwise "document".
    """
    ext = Path(filename).suffix.lower()
    if ext in {".mp4", ".mov", ".mkv", ".webm"}:
        return "video"
    if ext in {".mp3", ".wav", ".m4a"}:
        return "audio"
    if ext in {".txt", ".md"}:
        return "text"
    return "document"


def read_pdf_author(path: Path) -> str:
    """The author from a PDF's metadata: its author field, or else "..., by Name" at the end of its title
    (as in Project Gutenberg files, e.g. "The Project Gutenberg eBook of Successful Stock Speculation, by J. J. Butler").

    Returns:
        The author, or "" if the PDF names none or cannot be read.
    """
    try:
        with pymupdf.open(path) as doc:
            meta = doc.metadata or {}
    except Exception:  # not a readable PDF: no author
        return ""
    author = (meta.get("author") or "").strip()
    if not author:
        match = re.search(r",? by ([^,;]+?)(?:--.*)?$", meta.get("title") or "", re.IGNORECASE)
        author = match.group(1).strip() if match else ""
    return author[:120]
