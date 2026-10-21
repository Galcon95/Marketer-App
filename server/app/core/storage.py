"""File storage for uploaded sources: server/assets/uploads/{project_id}/{source_id}/{filename},
and for generated assets: server/assets/generated/{project_id}/{asset_id}.json.

Each source directory also holds META_FILENAME, the source's record as JSON, and after ingestion
CHUNKS_FILENAME with its chunks. The upload directory
is the single source of truth: load_sources() rebuilds all source records from it on startup, and
deleting a source deletes its directory, so the GUI and the files on disk always match.
"""

import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from pydantic import ValidationError

from app.core.config import DATA_DIR
from app.core.schemas import Asset, BookSummary, Chunk, Source, SourceKind

logger = logging.getLogger(__name__)

UPLOAD_DIR = DATA_DIR / "uploads"
# Generated marketing assets: assets/generated/{project_id}/{asset_id}.json
GENERATED_DIR = DATA_DIR / "generated"

# Source record stored next to the uploaded file. It starts with "." and safe_filename strips
# leading dots from uploads, so it can never collide with an uploaded file.
META_FILENAME = ".source.json"
# Chunks produced by ingestion, one JSON object per line (same dot-prefix reasoning as above).
CHUNKS_FILENAME = ".chunks.jsonl"
# Book summary (summary.py), created on demand.
SUMMARY_FILENAME = ".summary.json"
# Cover image of the book (ingestion.make_cover), shown in the GUI.
COVER_FILENAME = ".cover.png"

ALLOWED_EXTENSIONS = {".pdf"}  # widen when other formats get an ingestion path (EPUB, DOCX, video, ...)
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB
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


def save_upload(stream: BinaryIO, filename: str, project_id: str, source_id: str) -> tuple[Path, int]:
    """Validate and stream an upload to disk. Returns (path, size). Leaves nothing behind on failure.

    Checks the extension first, then creates a fresh directory for the source and copies the stream
    in CHUNK_BYTES pieces so large files never sit in memory as a whole. While copying it checks that
    the first bytes match the expected file signature and that the total size stays under
    MAX_UPLOAD_BYTES. On any error (including client disconnects) the source directory is removed
    before the exception is re-raised.

    Args:
        stream: Readable binary file object with the upload content (e.g. UploadFile.file).
        filename: Already sanitized file name (see safe_filename); its extension decides the type.
        project_id: Project the source belongs to; first directory level.
        source_id: New, unique source id; second directory level. Must not exist yet.

    Returns:
        Tuple of the path of the stored file and its size in bytes.

    Raises:
        UploadError: 415 for an unsupported extension or wrong content signature,
            413 when the file exceeds MAX_UPLOAD_BYTES, 400 when the file is empty.
        FileExistsError: If the directory for source_id already exists.
    """
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise UploadError(415, f"Unsupported file type '{ext or 'none'}'. Allowed: {allowed}")

    target_dir = UPLOAD_DIR / project_id / source_id
    target_dir.mkdir(parents=True, exist_ok=False)
    target = target_dir / filename
    size = 0
    try:
        with target.open("wb") as out:
            while chunk := stream.read(CHUNK_BYTES):
                if size == 0 and ext in SIGNATURES and not chunk.startswith(SIGNATURES[ext]):
                    raise UploadError(415, f"The file content is not a valid {ext[1:].upper()}")
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise UploadError(413, f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
                out.write(chunk)
        if size == 0:
            raise UploadError(400, "File is empty")
    except BaseException:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise
    return target, size


def delete_source_files(project_id: str, source_id: str) -> None:
    """Delete the stored file(s) of a source by removing its whole upload directory.

    Missing directories are ignored, so it is safe to call for sources that have no files
    (e.g. after an interrupted upload).

    Args:
        project_id: Project the source belongs to.
        source_id: Source whose directory should be removed.
    """
    shutil.rmtree(UPLOAD_DIR / project_id / source_id, ignore_errors=True)


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


def write_source_meta(source: Source) -> None:
    """Save a source record as JSON in its upload directory, replacing any previous version.

    Call it whenever a source changes (after upload, and later on every ingestion status change).
    Writes to a temporary file first and then renames it, so a crash mid-write never leaves a
    half-written record behind.

    Args:
        source: The source to save; its directory must already exist.

    Raises:
        OSError: If the file cannot be written.
    """
    source_dir = UPLOAD_DIR / source.project_id / source.id
    tmp = source_dir / f"{META_FILENAME}.tmp"
    tmp.write_text(source.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(source_dir / META_FILENAME)


def cover_path(source: Source) -> Path:
    """Path of a book's cover image (it may not exist yet, see ingestion.make_cover)."""
    return UPLOAD_DIR / source.project_id / source.id / COVER_FILENAME


def source_file_path(source: Source) -> Path:
    """Path of the uploaded file of a source (the file may be missing, e.g. if deleted by hand).

    Args:
        source: The source whose file path to build.
    """
    return UPLOAD_DIR / source.project_id / source.id / source.filename


def write_chunks(source: Source, chunks: list[Chunk]) -> None:
    """Save the chunks of a source in its upload directory, replacing any previous chunks.

    Written to a temporary file first and then renamed, like write_source_meta.

    Args:
        source: The source the chunks belong to; its directory must already exist.
        chunks: All chunks of the source, in reading order.

    Raises:
        OSError: If the file cannot be written.
    """
    source_dir = UPLOAD_DIR / source.project_id / source.id
    tmp = source_dir / f"{CHUNKS_FILENAME}.tmp"
    tmp.write_text("".join(c.model_dump_json() + "\n" for c in chunks), encoding="utf-8")
    tmp.replace(source_dir / CHUNKS_FILENAME)


def load_chunks(source: Source) -> list[Chunk] | None:
    """Read the saved chunks of a source.

    Args:
        source: The source whose chunks to read.

    Returns:
        The chunks in reading order, or None if the file is missing or cannot be parsed.
    """
    path = UPLOAD_DIR / source.project_id / source.id / CHUNKS_FILENAME
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        return [Chunk.model_validate_json(line) for line in lines if line.strip()]
    except (OSError, ValidationError):
        return None


def write_summary(source: Source, summary: BookSummary) -> None:
    """Save the summary of a book in its upload directory, replacing any previous one.

    Args:
        source: The book the summary belongs to; its directory must already exist.
        summary: The summary to save.

    Raises:
        OSError: If the file cannot be written.
    """
    source_dir = UPLOAD_DIR / source.project_id / source.id
    tmp = source_dir / f"{SUMMARY_FILENAME}.tmp"
    tmp.write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(source_dir / SUMMARY_FILENAME)


def load_summary(source: Source) -> BookSummary | None:
    """Read the saved summary of a book, or None if there is none (or it cannot be parsed)."""
    try:
        return BookSummary.model_validate_json((UPLOAD_DIR / source.project_id / source.id / SUMMARY_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValidationError):
        return None


def write_asset(asset: Asset) -> None:
    """Save a generated asset as JSON so it survives server restarts.

    Written to a temporary file first and then renamed, like write_source_meta.

    Args:
        asset: The asset to save.

    Raises:
        OSError: If the file cannot be written.
    """
    target_dir = GENERATED_DIR / asset.project_id
    target_dir.mkdir(parents=True, exist_ok=True)
    tmp = target_dir / f".{asset.id}.json.tmp"
    tmp.write_text(asset.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(target_dir / f"{asset.id}.json")


def delete_asset(asset: Asset) -> None:
    """Delete the saved file of a generated asset, if any."""
    (GENERATED_DIR / asset.project_id / f"{asset.id}.json").unlink(missing_ok=True)


def load_assets() -> dict[str, Asset]:
    """Read all saved generated assets (called once on server startup); unreadable files are skipped.

    Returns:
        Assets by id, oldest first.
    """
    assets: list[Asset] = []
    for path in GENERATED_DIR.glob("*/*.json"):
        try:
            assets.append(Asset.model_validate_json(path.read_text(encoding="utf-8")))
        except (OSError, ValidationError):
            logger.warning("Skipping unreadable asset file %s", path)
    assets.sort(key=lambda a: a.created_at)
    return {a.id: a for a in assets}


def load_sources() -> dict[str, Source]:
    """Rebuild all source records from the upload directory (called once on server startup).

    Looks at every {project_id}/{source_id} directory. Uses its META_FILENAME when it is valid;
    otherwise (missing, corrupt, or uploaded before records were saved) recovers the record from
    the uploaded file itself. Directories without exactly one uploaded file are skipped with a
    warning and left untouched on disk.

    Returns:
        Source records by id, oldest first.
    """
    sources: list[Source] = []
    for source_dir in sorted(p for p in UPLOAD_DIR.glob("*/*") if p.is_dir()):
        project_id, source_id = source_dir.parent.name, source_dir.name
        source = _read_source_meta(source_dir, project_id, source_id) or _recover_source_meta(source_dir, project_id, source_id)
        if source is None:
            logger.warning("Skipping %s: no uploaded file found", source_dir)
        else:
            sources.append(source)
    sources.sort(key=lambda s: s.created_at)
    return {s.id: s for s in sources}


def _read_source_meta(source_dir: Path, project_id: str, source_id: str) -> Source | None:
    """Read and check the saved record of one source directory.

    Args:
        source_dir: The directory {project_id}/{source_id}.
        project_id: Project id taken from the directory path.
        source_id: Source id taken from the directory path.

    Returns:
        The record, or None if it is missing, unreadable, invalid, does not match the directory
        path, or its file no longer exists.
    """
    try:
        source = Source.model_validate_json((source_dir / META_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValidationError):
        return None
    if (source.project_id, source.id) != (project_id, source_id) or not (source_dir / source.filename).is_file():
        return None
    return source


def _recover_source_meta(source_dir: Path, project_id: str, source_id: str) -> Source | None:
    """Recreate the record of a source directory from its uploaded file and save it.

    Uses the file's name, size and modification time; the status is "uploaded" because no
    ingestion results exist for it.

    Args:
        source_dir: The directory {project_id}/{source_id}.
        project_id: Project id taken from the directory path.
        source_id: Source id taken from the directory path.

    Returns:
        The recovered record, or None if the directory does not hold exactly one uploaded file.
    """
    files = [p for p in source_dir.iterdir() if p.is_file() and not p.name.startswith(".")]
    if len(files) != 1:
        return None
    stat = files[0].stat()
    source = Source(
        id=source_id,
        project_id=project_id,
        filename=files[0].name,
        kind=detect_kind(files[0].name),
        size_bytes=stat.st_size,
        status="uploaded",
        progress=100,
        chunk_count=0,
        created_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc),
    )
    try:
        write_source_meta(source)
    except OSError:
        logger.warning("Could not save recovered record for %s", source_dir)
    logger.info("Recovered source record for %s", source_dir)
    return source
