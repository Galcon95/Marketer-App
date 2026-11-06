"""Sources (uploaded books): upload, processing into chunks, listing, deletion, chunks, file and cover. The files
are in Supabase Storage (core/files.py), the records in the database."""

import logging
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response, StreamingResponse

from app.api.deps import llm_limits, owned_project, owned_source
from app.core import state as db
from app.core import files, storage
from app.core.limits import LIMITS
from app.core.schemas import Asset, ChunkPage, Conversation, Source, SourceDeletion
from app.db import records
from app.rag import ingestion
from app.rag.retrieval import source_name

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------- Sources (content upload & ingestion) ----------
@router.post("/projects/{project_id}/sources", response_model=Source, status_code=201,
             dependencies=[Depends(owned_project), Depends(llm_limits)])
def upload_source(project_id: str, background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """Store an uploaded file and start processing it into chunks in the background.

    Sanitizes the file name, streams the file into a temporary file via storage.save_upload (which validates
    type, signature and size and computes the content checksum), rejects a file whose content is already
    in the project (whatever its name), stores it in Supabase Storage, saves a Source with status "queued" in the
    database (if that fails, the stored file is removed again) and schedules ingestion.ingest_source to run after
    the response is sent. The temporary file is always deleted. Poll GET /sources/{id} to follow the progress.

    Args:
        project_id: Project to add the source to (path parameter). 404 if unknown.
        background_tasks: Injected by FastAPI; runs the ingestion after the response.
        file: The uploaded file (multipart/form-data field "file").

    Returns:
        The new Source record (status "queued").

    Raises:
        HTTPException: 404 for an unknown project (or another user's); 400/413/415 when the file is rejected;
            409 when the same file is already in the project or it has max_books books (limits.toml); 429 when a
            limit of llm_limits is reached (processing embeds the book); 500 when the file or its record cannot be
            saved (then nothing is kept).
    """
    if sum(1 for s in db.sources.values() if s.project_id == project_id) >= LIMITS.per_user.max_books:
        raise HTTPException(409, f"Your library is full: at most {LIMITS.per_user.max_books} books. "
                                 "Delete a book to add another one.")
    source_id = db.new_id("src")
    filename = storage.safe_filename(file.filename or "")
    try:
        upload, size, sha256 = storage.save_upload(file.file, filename)
    except storage.UploadError as e:
        raise HTTPException(e.status_code, e.detail) from e
    try:
        duplicate = next((s for s in db.sources.values() if s.project_id == project_id and s.sha256 == sha256), None)
        if duplicate:
            raise HTTPException(409, f"This file is already in your library as '{source_name(duplicate.id) or duplicate.filename}'.")
        source = Source(
            id=source_id,
            project_id=project_id,
            filename=filename,
            kind=storage.detect_kind(filename),
            size_bytes=size,
            status="queued",
            progress=0,
            chunk_count=0,
            created_at=db.now(),
            sha256=sha256,
        )
        if source.kind == "document":
            source.author = storage.read_pdf_author(upload)
        try:
            files.put(files.book_path(project_id, source_id, filename), upload, _media_type(filename))
        except OSError as e:  # FileStoreError
            logger.error("Could not store the upload %s: %s", source_id, e)
            raise HTTPException(500, "The file could not be stored, please try again.") from e
        try:
            records.add_source(source)
        except OSError as e:  # DatabaseError: the stored file is removed again
            _delete_files(source)
            raise HTTPException(500, "Could not save the uploaded file's record") from e
    finally:
        upload.unlink(missing_ok=True)
    db.sources[source.id] = source
    background_tasks.add_task(ingestion.ingest_source, source.id)
    return source


@router.post("/sources/{source_id}/ingest", response_model=Source, status_code=202,
             dependencies=[Depends(owned_source), Depends(llm_limits)])
def ingest_source(source_id: str, background_tasks: BackgroundTasks, source: Source = Depends(owned_source)):
    """(Re)build the chunks of an uploaded source in the background: Process / Re-index / Retry.

    Sets the source to "queued" and schedules ingestion.ingest_source. Existing chunks stay
    available until the new ones are ready.

    Args:
        source_id: Id of the source (path parameter). 404 if unknown.
        background_tasks: Injected by FastAPI; runs the ingestion after the response.

    Returns:
        The source with status "queued".

    Raises:
        HTTPException: 409 if it is already being processed or its stored file is missing.
    """
    if source.status in ingestion.PROCESSING_STATUSES:
        raise HTTPException(409, f"'{source.filename}' is already being processed")
    try:
        stored = files.exists(files.book_path(source.project_id, source.id, source.filename))
    except OSError as e:  # FileStoreError
        raise HTTPException(503, "The file storage cannot be reached, please try again.") from e
    if not stored:
        raise HTTPException(409, f"'{source.filename}' has no stored file to process. Delete it and upload it again.")
    source = source.model_copy(update={"status": "queued", "progress": 0, "error": None})
    try:
        saved = records.update_source(source)
    except OSError as e:  # DatabaseError
        raise HTTPException(500, "Could not save the source's record") from e
    if not saved:  # deleted meanwhile
        raise HTTPException(404, "Source not found.")
    db.sources[source_id] = source
    background_tasks.add_task(ingestion.ingest_source, source_id)
    return source


@router.get("/projects/{project_id}/sources", response_model=list[Source], dependencies=[Depends(owned_project)])
def list_sources(project_id: str):
    """List all sources of a project.

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
    """
    return [s for s in db.sources.values() if s.project_id == project_id]


@router.get("/sources/{source_id}", response_model=Source)
def get_source(source: Source = Depends(owned_source)):
    """Return one source, e.g. to poll its ingestion status. 404 if unknown."""
    return source


@router.get("/sources/{source_id}/deletion", response_model=SourceDeletion)
def preview_deletion(source: Source = Depends(owned_source)):
    """What deleting this book would remove besides the book itself (for the confirmation): the generated assets
    made only from it and the chats that only used its passages. Nothing is deleted. 404 if unknown."""
    assets, conversations = _dependents(source)
    return SourceDeletion(source_id=source.id, name=source_name(source.id) or source.filename,
                          assets=len(assets), conversations=len(conversations))


@router.delete("/sources/{source_id}", response_model=SourceDeletion)
def delete_source(source_id: str, source: Source = Depends(owned_source)):
    """Delete a book with everything that belongs only to it: its stored files (PDF, cover, summary), chunks and
    vectors, the generated assets made only from it (incl. its campaign kits) and the chats that only used its
    passages. Assets and chats that also draw on other books are kept. Works while the book is processing.

    Args:
        source_id: Id of the source (path parameter). 404 if unknown.

    Returns:
        What was removed besides the book itself.

    Raises:
        HTTPException: 500 if it cannot be deleted from the database (then nothing is deleted).
    """
    name = source_name(source.id) or source.filename
    assets, conversations = _dependents(source)
    # The database first, in one transaction (book, summary, assets, chats): if that fails, everything is still there.
    try:
        records.delete_source(source_id, (a.id for a in assets), (c.id for c in conversations))
    except OSError as e:  # DatabaseError
        raise HTTPException(500, "The book could not be deleted, please try again.") from e
    # Then the record in memory, so a running ingestion sees the deletion and stops.
    db.sources.pop(source_id, None)
    ingestion.delete_source_data(source)
    _delete_files(source)
    for asset in assets:
        db.assets.pop(asset.id, None)
    for conversation in conversations:
        db.conversations.pop(conversation.id, None)
    return SourceDeletion(source_id=source_id, name=name, assets=len(assets), conversations=len(conversations))


def _dependents(source: Source) -> tuple[list[Asset], list[Conversation]]:
    """The generated assets made only from this book (their source_ids are exactly this book; campaign kits for it
    too) and the chats in which every retrieved passage comes from this book."""
    assets = [a for a in db.assets.values() if a.project_id == source.project_id and a.source_ids == [source.id]]
    conversations = [
        c for c in db.conversations.values()
        if c.project_id == source.project_id and c.turns
        and all(hit.chunk.source_id == source.id for turn in c.turns for hit in turn.passages)
    ]
    return assets, conversations


@router.get("/sources/{source_id}/chunks", response_model=ChunkPage, dependencies=[Depends(owned_source)])
def list_chunks(source_id: str, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    """Return one page of the chunks produced from a source.

    Args:
        source_id: Id of the source (path parameter). 404 if unknown.
        offset: Index of the first chunk to return (query parameter, >= 0).
        limit: Maximum number of chunks to return (query parameter, 1-100).

    Returns:
        A ChunkPage with the requested slice and the total chunk count.
    """
    items = [c for c in db.chunks.values() if c.source_id == source_id]
    return ChunkPage(items=items[offset:offset + limit], total=len(items), offset=offset, limit=limit)


@router.get("/sources/{source_id}/file", response_class=StreamingResponse)
def get_source_file(source: Source = Depends(owned_source)):
    """Return the uploaded file itself (e.g. the PDF), for viewing in the browser (not as a download), streamed
    from Supabase Storage.

    Browsers' PDF viewers accept a page in the link, e.g. /sources/{id}/file#page=13, which the GUI
    uses to open a citation at its page.

    Args:
        source_id: Id of the source (path parameter). 404 if unknown.

    Raises:
        HTTPException: 404 if the source is unknown or its file is missing; 503 if Storage cannot be reached.
    """
    try:
        pieces = files.stream(files.book_path(source.project_id, source.id, source.filename))
    except OSError as e:  # FileStoreError
        raise HTTPException(503, "The file storage cannot be reached, please try again.") from e
    if pieces is None:
        raise HTTPException(404, "The file of this source is missing")
    return StreamingResponse(pieces, media_type=_media_type(source.filename),
                             headers={"Content-Disposition": _inline(source.filename)})


@router.get("/sources/{source_id}/cover", response_class=Response)
def get_cover(source: Source = Depends(owned_source)):
    """Return the cover image (PNG) of a book, creating it on first request if needed.

    Args:
        source_id: Id of the source (path parameter). 404 if unknown.

    Raises:
        HTTPException: 404 if the source is unknown or no cover can be made (no stored PDF); 503 if Storage cannot
            be reached.
    """
    try:
        cover = ingestion.cover(source)
    except OSError as e:  # FileStoreError
        raise HTTPException(503, "The file storage cannot be reached, please try again.") from e
    if cover is None:
        raise HTTPException(404, "No cover available")
    return Response(cover, media_type="image/png")


def _media_type(filename: str) -> str:
    return "application/pdf" if filename.lower().endswith(".pdf") else "application/octet-stream"


def _inline(filename: str) -> str:
    """Content-Disposition for showing a file in the browser, with its name (RFC 6266; any characters)."""
    return f"inline; filename*=UTF-8''{quote(filename)}"


def _delete_files(source: Source) -> None:
    """Delete a source's stored files (book, cover); a failure is only logged (the files are then orphaned in
    Storage, but no longer reachable through the app)."""
    try:
        files.delete_source_files(source.project_id, source.id)
    except OSError as e:  # FileStoreError
        logger.warning("Could not delete the stored files of %s: %s", source.id, e)
