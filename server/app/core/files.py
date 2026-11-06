"""Uploaded files (books) and their covers in Supabase Storage: a private bucket, read and written only by the server.

    books/{project_id}/{source_id}/book.pdf    the uploaded file (its original name is in the source record)
    books/{project_id}/{source_id}/cover.png   its cover image (ingestion.make_cover)

Fixed object names, because Storage accepts fewer characters in names than a file system (the original file name
may contain any letter); the GUI shows the name from the database. The bucket is created by migration 0006 with
the upload limit and the allowed types; it is private, and Storage's row-level security has no policy for it, so
only the server reaches it, with the project's secret key (SUPABASE_SECRET_KEY, never sent to the browser).

The server talks to Storage's REST API with httpx. PyMuPDF needs a file on disk, so processing downloads a book
to a temporary file (download) and deletes it afterwards. Tests replace the backend with an in-memory one (use).
"""

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx

from app.core.config import SUPABASE_SECRET_KEY, SUPABASE_URL

logger = logging.getLogger(__name__)

BUCKET = "books"
CHUNK_BYTES = 1024 * 1024  # streamed in 1 MB pieces, never a whole book in memory
TIMEOUT = httpx.Timeout(30.0, read=120.0)  # a 50 MB book over a slow line


class FileStoreError(OSError):
    """Storage cannot be reached or refused a request. An OSError like a failed file write, so the callers'
    "could not be saved" handling (500) covers it."""


def book_path(project_id: str, source_id: str, filename: str) -> str:
    """Object name of a source's uploaded file: book.<its extension>."""
    return f"{project_id}/{source_id}/book{Path(filename).suffix.lower()}"


def cover_path(project_id: str, source_id: str) -> str:
    """Object name of a book's cover image."""
    return f"{project_id}/{source_id}/cover.png"


class Backend(Protocol):
    def put(self, path: str, data: bytes | Path, content_type: str) -> None: ...
    def get(self, path: str) -> bytes | None: ...
    def stream(self, path: str) -> Iterator[bytes] | None: ...
    def names(self, folder: str) -> list[str]: ...
    def delete(self, paths: list[str]) -> None: ...


class SupabaseStorage:
    """The Storage REST API of the Supabase project (SUPABASE_URL), with the secret key."""

    def _client(self) -> httpx.Client:
        if not (SUPABASE_URL and SUPABASE_SECRET_KEY):
            raise FileStoreError("SUPABASE_URL and SUPABASE_SECRET_KEY must be set (server/.env) to store files.")
        return httpx.Client(base_url=f"{SUPABASE_URL}/storage/v1", timeout=TIMEOUT,
                            headers={"apikey": SUPABASE_SECRET_KEY, "Authorization": f"Bearer {SUPABASE_SECRET_KEY}"})

    @staticmethod
    def _object(path: str) -> str:
        return f"/object/{BUCKET}/{quote(path)}"

    @staticmethod
    def _check(response: httpx.Response, action: str) -> None:
        if response.is_error:
            raise FileStoreError(f"Storage refused to {action} ({response.status_code}): {response.text[:200]}")

    def put(self, path: str, data: bytes | Path, content_type: str) -> None:
        """Upload (or replace) an object; a Path is streamed from disk."""
        try:
            with self._client() as client:
                if isinstance(data, Path):
                    with data.open("rb") as f:
                        response = client.post(self._object(path), content=_read(f),
                                               headers={"Content-Type": content_type, "x-upsert": "true",
                                                        "Content-Length": str(data.stat().st_size)})
                else:
                    response = client.post(self._object(path), content=data,
                                           headers={"Content-Type": content_type, "x-upsert": "true"})
        except httpx.HTTPError as e:
            raise FileStoreError(f"Storage cannot be reached: {e}") from e
        self._check(response, f"store {path}")

    def get(self, path: str) -> bytes | None:
        """The whole object (small ones, e.g. covers), or None if there is none."""
        try:
            with self._client() as client:
                response = client.get(self._object(path))
        except httpx.HTTPError as e:
            raise FileStoreError(f"Storage cannot be reached: {e}") from e
        if response.status_code in (400, 404):  # Storage answers 400 "Object not found" for a missing object
            return None
        self._check(response, f"read {path}")
        return response.content

    def stream(self, path: str) -> Iterator[bytes] | None:
        """The object in pieces (large ones, e.g. books), or None if there is none. The connection stays open until
        the iterator is used up or closed."""
        client = self._client()
        try:
            response = client.send(client.build_request("GET", self._object(path)), stream=True)
        except httpx.HTTPError as e:
            client.close()
            raise FileStoreError(f"Storage cannot be reached: {e}") from e
        if response.status_code in (400, 404):
            response.close()
            client.close()
            return None
        if response.is_error:
            response.read()
            response.close()
            client.close()
            self._check(response, f"read {path}")

        def pieces() -> Iterator[bytes]:
            try:
                yield from response.iter_bytes(CHUNK_BYTES)
            finally:
                response.close()
                client.close()
        return pieces()

    def names(self, folder: str) -> list[str]:
        """Names of the objects directly in a folder, e.g. ["book.pdf", "cover.png"]."""
        try:
            with self._client() as client:
                response = client.post(f"/object/list/{BUCKET}", json={"prefix": folder.rstrip("/") + "/", "limit": 100})
        except httpx.HTTPError as e:
            raise FileStoreError(f"Storage cannot be reached: {e}") from e
        self._check(response, f"list {folder}")
        return [item["name"] for item in response.json() if item.get("id")]  # folders have no id

    def delete(self, paths: list[str]) -> None:
        """Delete these objects; missing ones are ignored."""
        if not paths:
            return
        try:
            with self._client() as client:
                response = client.request("DELETE", f"/object/{BUCKET}", json={"prefixes": paths})
        except httpx.HTTPError as e:
            raise FileStoreError(f"Storage cannot be reached: {e}") from e
        self._check(response, "delete files")


def _read(f) -> Iterator[bytes]:
    while chunk := f.read(CHUNK_BYTES):
        yield chunk


_backend: Backend = SupabaseStorage()


def use(backend: Backend) -> None:
    """Use another backend from now on (tests: an in-memory one)."""
    global _backend
    _backend = backend


# ---------- Public API (all raise FileStoreError if Storage cannot be reached or refuses) ----------
def put(path: str, data: bytes | Path, content_type: str) -> None:
    """Store a file (bytes, or a file on disk, which is streamed), replacing one with the same name."""
    _backend.put(path, data, content_type)


def get(path: str) -> bytes | None:
    """A small file's content (e.g. a cover), or None if it does not exist."""
    return _backend.get(path)


def stream(path: str) -> Iterator[bytes] | None:
    """A large file's content in pieces (e.g. a book for the browser), or None if it does not exist."""
    return _backend.stream(path)


def download(path: str, target: Path) -> bool:
    """Save a file to disk (e.g. a book for PyMuPDF); False if it does not exist."""
    pieces = _backend.stream(path)
    if pieces is None:
        return False
    with target.open("wb") as out:
        for piece in pieces:
            out.write(piece)
    return True


def exists(path: str) -> bool:
    """True if the file exists."""
    folder, _, name = path.rpartition("/")
    return name in _backend.names(folder)


def delete_source_files(project_id: str, source_id: str) -> None:
    """Delete all stored files of a source (its book and cover)."""
    folder = f"{project_id}/{source_id}"
    _backend.delete([f"{folder}/{name}" for name in _backend.names(folder)])
