"""Sources (uploaded books): upload, processing into chunks, listing, deletion, chunks, file and cover."""

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import get_project_or_404, get_source_or_404
from app.core import state as db
from app.core import storage
from app.core.schemas import ChunkPage, Source
from app.rag import ingestion

router = APIRouter()


# ---------- Sources (content upload & ingestion) ----------
@router.post("/projects/{project_id}/sources", response_model=Source, status_code=201)
def upload_source(project_id: str, background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """Store an uploaded file on disk and start processing it into chunks in the background.

    Sanitizes the file name, streams the file to disk via storage.save_upload (which validates
    type, signature and size), then registers a Source with status "queued", saves its record
    next to the file so it is restored after a server restart, and schedules ingestion.ingest_source
    to run after the response is sent. Poll GET /sources/{id} to follow the progress.

    Args:
        project_id: Project to add the source to (path parameter). 404 if unknown.
        background_tasks: Injected by FastAPI; runs the ingestion after the response.
        file: The uploaded file (multipart/form-data field "file").

    Returns:
        The new Source record (status "queued").

    Raises:
        HTTPException: 404 for an unknown project; 400/413/415 when storage rejects the file;
            500 when the record cannot be saved (the stored file is removed again).
    """
    get_project_or_404(project_id)
    source_id = db.new_id("src")
    filename = storage.safe_filename(file.filename or "")
    try:
        _, size = storage.save_upload(file.file, filename, project_id, source_id)
    except storage.UploadError as e:
        raise HTTPException(e.status_code, e.detail) from e
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
    )
    try:
        storage.write_source_meta(source)
    except OSError as e:
        storage.delete_source_files(project_id, source_id)
        raise HTTPException(500, "Could not save the uploaded file's record") from e
    db.sources[source.id] = source
    background_tasks.add_task(ingestion.ingest_source, source.id)
    return source


@router.post("/sources/{source_id}/ingest", response_model=Source, status_code=202)
def ingest_source(source_id: str, background_tasks: BackgroundTasks):
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
    source = get_source_or_404(source_id)
    if source.status in ingestion.PROCESSING_STATUSES:
        raise HTTPException(409, f"'{source.filename}' is already being processed")
    if not storage.source_file_path(source).is_file():
        raise HTTPException(409, f"'{source.filename}' has no stored file to process. Delete it and upload it again.")
    source = source.model_copy(update={"status": "queued", "progress": 0, "error": None})
    try:
        storage.write_source_meta(source)
    except OSError as e:
        raise HTTPException(500, "Could not save the source's record") from e
    db.sources[source_id] = source
    background_tasks.add_task(ingestion.ingest_source, source_id)
    return source


@router.get("/projects/{project_id}/sources", response_model=list[Source])
def list_sources(project_id: str):
    """List all sources of a project.

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
    """
    get_project_or_404(project_id)
    return [s for s in db.sources.values() if s.project_id == project_id]


@router.get("/sources/{source_id}", response_model=Source)
def get_source(source_id: str):
    """Return one source, e.g. to poll its ingestion status.

    Args:
        source_id: Id of the source (path parameter). 404 if unknown.
    """
    return get_source_or_404(source_id)


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: str):
    """Delete a source with its stored files, chunks and vectors (also while it is processing).

    Args:
        source_id: Id of the source (path parameter). 404 if unknown.
    """
    source = get_source_or_404(source_id)
    # Remove the record first, so a running ingestion sees the deletion and stops writing.
    db.sources.pop(source_id, None)
    ingestion.delete_source_data(source)
    storage.delete_source_files(source.project_id, source_id)


@router.get("/sources/{source_id}/chunks", response_model=ChunkPage)
def list_chunks(source_id: str, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    """Return one page of the chunks produced from a source.

    Args:
        source_id: Id of the source (path parameter). 404 if unknown.
        offset: Index of the first chunk to return (query parameter, >= 0).
        limit: Maximum number of chunks to return (query parameter, 1-100).

    Returns:
        A ChunkPage with the requested slice and the total chunk count.
    """
    get_source_or_404(source_id)
    items = [c for c in db.chunks.values() if c.source_id == source_id]
    return ChunkPage(items=items[offset:offset + limit], total=len(items), offset=offset, limit=limit)


@router.get("/sources/{source_id}/file", response_class=FileResponse)
def get_source_file(source_id: str):
    """Return the uploaded file itself (e.g. the PDF), for viewing in the browser (not as a download).

    Browsers' PDF viewers accept a page in the link, e.g. /sources/{id}/file#page=13, which the GUI
    uses to open a citation at its page.

    Args:
        source_id: Id of the source (path parameter). 404 if unknown.

    Raises:
        HTTPException: 404 if the source is unknown or its file is missing.
    """
    source = get_source_or_404(source_id)
    path = storage.source_file_path(source)
    if not path.is_file():
        raise HTTPException(404, "The file of this source is missing")
    media_type = "application/pdf" if path.suffix.lower() == ".pdf" else None
    return FileResponse(path, media_type=media_type, filename=source.filename, content_disposition_type="inline")


@router.get("/sources/{source_id}/cover", response_class=FileResponse)
def get_cover(source_id: str):
    """Return the cover image (PNG) of a book, creating it on first request if needed.

    Args:
        source_id: Id of the source (path parameter). 404 if unknown.

    Raises:
        HTTPException: 404 if the source is unknown or no cover can be made (no stored PDF).
    """
    source = get_source_or_404(source_id)
    if not storage.source_file_path(source).is_file() or not ingestion.make_cover(source):
        raise HTTPException(404, "No cover available")
    return FileResponse(storage.cover_path(source), media_type="image/png")
