"""Marketer App API. Uploads are stored for real (storage.py); everything else returns dummy data
(see dummy_data.py)."""

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

import dummy_data as db
import storage
from schemas import (
    Asset, Chunk, ChunkPage, GenerateRequest, Health, Project, ProjectCreate, SearchHit,
    SearchRequest, SearchResponse, ServiceStatus, Source, VerifyItem,
    VerifyRequest, VerifyResponse,
)

# Restore uploaded sources from disk so they survive server restarts (listed after the demo sources).
db.sources.update(storage.load_sources())

app = FastAPI(title="Marketer App API")

# Allow the Next.js dev client (port 3000) to call the API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Helpers ----------
def get_project_or_404(project_id: str) -> Project:
    """Look up a project by id, or abort the request with 404 if it does not exist.

    Args:
        project_id: Id of the project to find.

    Returns:
        The stored Project (without computed counts).

    Raises:
        HTTPException: 404 when no project has this id.
    """
    project = db.projects.get(project_id)
    if project is None:
        raise HTTPException(404, f"Project '{project_id}' not found")
    return project


def get_source_or_404(source_id: str) -> Source:
    """Look up a source by id, or abort the request with 404 if it does not exist.

    Args:
        source_id: Id of the source to find.

    Returns:
        The stored Source.

    Raises:
        HTTPException: 404 when no source has this id.
    """
    source = db.sources.get(source_id)
    if source is None:
        raise HTTPException(404, f"Source '{source_id}' not found")
    return source


def with_counts(project: Project) -> Project:
    """Return a copy of a project with source_count, chunk_count and asset_count filled in.

    Counts are computed on every call by scanning the in-memory stores, so they are always
    current; the stored project itself is not modified.

    Args:
        project: The project to count for.

    Returns:
        A new Project instance with up-to-date counts.
    """
    source_ids = {s.id for s in db.sources.values() if s.project_id == project.id}
    return project.model_copy(update={
        "source_count": len(source_ids),
        "chunk_count": sum(1 for c in db.chunks.values() if c.source_id in source_ids),
        "asset_count": sum(1 for a in db.assets.values() if a.project_id == project.id),
    })


def project_chunks(project_id: str, source_ids: list[str] | None = None) -> list[Chunk]:
    """Collect all chunks of a project, optionally limited to some of its sources.

    Builds the set of the project's source ids, intersects it with source_ids when given
    (so ids from other projects are ignored), and returns the chunks of those sources.

    Args:
        project_id: Project whose chunks to return.
        source_ids: Optional filter; None or an empty list means all sources of the project.

    Returns:
        The matching chunks in storage order.
    """
    allowed = {s.id for s in db.sources.values() if s.project_id == project_id}
    if source_ids:
        allowed &= set(source_ids)
    return [c for c in db.chunks.values() if c.source_id in allowed]


# ---------- Basic ----------
@app.get("/")
def root():
    """Smoke-test endpoint: returns a fixed greeting to show the server is reachable."""
    return {"message": "Hello, World!"}


@app.get("/test")
def test():
    """Second smoke-test endpoint used by the client to check the connection."""
    return {"message": "Hello, Server World!"}


@app.get("/health", response_model=Health)
def health():
    """Report the status of the API and its dependencies.

    The vector database and LLM are not connected yet, so they are always reported as down;
    overall `ok` reflects only the API itself.
    """
    services = [
        ServiceStatus(name="api", ok=True, detail="running"),
        ServiceStatus(name="vector_db", ok=False, detail="dummy · not connected"),
        ServiceStatus(name="llm", ok=False, detail="dummy · not connected"),
    ]
    return Health(ok=services[0].ok, services=services)


# ---------- Projects ----------
@app.post("/projects", response_model=Project, status_code=201)
def create_project(body: ProjectCreate):
    """Create a new, empty project.

    Args:
        body: Name and optional description of the project.

    Returns:
        The created project with a new "prj_" id and zero counts.
    """
    project = Project(id=db.new_id("prj"), name=body.name, description=body.description, created_at=db.now())
    db.projects[project.id] = project
    return project


@app.get("/projects", response_model=list[Project])
def list_projects():
    """List all projects, each with its current source, chunk and asset counts."""
    return [with_counts(p) for p in db.projects.values()]


@app.get("/projects/{project_id}", response_model=Project)
def get_project(project_id: str):
    """Return one project with its current counts.

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
    """
    return with_counts(get_project_or_404(project_id))


# ---------- Sources (content upload & ingestion) ----------
@app.post("/projects/{project_id}/sources", response_model=Source, status_code=201)
def upload_source(project_id: str, file: UploadFile = File(...)):
    """Store an uploaded file on disk. Ingestion (parse → chunk → embed) is not implemented yet.

    Sanitizes the file name, streams the file to disk via storage.save_upload (which validates
    type, signature and size), then registers a Source with status "uploaded" and saves its record
    next to the file so it is restored after a server restart.

    Args:
        project_id: Project to add the source to (path parameter). 404 if unknown.
        file: The uploaded file (multipart/form-data field "file").

    Returns:
        The new Source record.

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
        status="uploaded",
        progress=100,
        chunk_count=0,
        created_at=db.now(),
    )
    try:
        storage.write_source_meta(source)
    except OSError as e:
        storage.delete_source_files(project_id, source_id)
        raise HTTPException(500, "Could not save the uploaded file's record") from e
    db.sources[source.id] = source
    return source


@app.get("/projects/{project_id}/sources", response_model=list[Source])
def list_sources(project_id: str):
    """List all sources of a project.

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
    """
    get_project_or_404(project_id)
    return [s for s in db.sources.values() if s.project_id == project_id]


@app.get("/sources/{source_id}", response_model=Source)
def get_source(source_id: str):
    """Return one source, e.g. to poll its ingestion status.

    Args:
        source_id: Id of the source (path parameter). 404 if unknown.
    """
    return get_source_or_404(source_id)


@app.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: str):
    """Delete a source together with its stored files and all of its chunks.

    Args:
        source_id: Id of the source (path parameter). 404 if unknown.
    """
    source = get_source_or_404(source_id)
    storage.delete_source_files(source.project_id, source_id)
    del db.sources[source_id]
    for chunk_id in [c.id for c in db.chunks.values() if c.source_id == source_id]:
        del db.chunks[chunk_id]


# ---------- Chunks & search (RAG retrieval) ----------
@app.get("/sources/{source_id}/chunks", response_model=ChunkPage)
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


@app.post("/projects/{project_id}/search", response_model=SearchResponse)
def search(project_id: str, body: SearchRequest):
    """Search a project's chunks for passages relevant to a query (dummy implementation).

    Currently returns the first k chunks of the project with made-up, decreasing scores;
    the query text is not used yet.

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
        body: Query text, number of hits k and optional source filter.

    Returns:
        The query and up to k hits, best first.
    """
    get_project_or_404(project_id)
    candidates = project_chunks(project_id, body.source_ids)[: body.k]
    # Dummy scores: descending from 0.94, no real similarity yet.
    hits = [SearchHit(chunk=c, score=round(0.94 - i * 0.07, 2)) for i, c in enumerate(candidates)]
    return SearchResponse(query=body.query, hits=hits)


# ---------- Generation & assets ----------
@app.post("/projects/{project_id}/generate", response_model=Asset, status_code=201)
def generate(project_id: str, body: GenerateRequest):
    """Generate a marketing asset from a brief and store it in the project (dummy implementation).

    When grounded, cites up to two of the project's chunks (at most k); otherwise no citations.
    The text is a placeholder that echoes the asset type, mode and brief; no LLM is called yet.

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
        body: Asset type, brief, grounded flag and number of context chunks k.

    Returns:
        The newly created Asset.
    """
    get_project_or_404(project_id)
    citations = []
    if body.grounded:
        citations = [db.dummy_citation(c, round(0.94 - i * 0.07, 2))
                     for i, c in enumerate(project_chunks(project_id)[: min(body.k, 2)])]
    mode = "grounded (RAG)" if body.grounded else "zero-shot"
    asset = Asset(
        id=db.new_id("ast"),
        project_id=project_id,
        asset_type=body.asset_type,
        grounded=body.grounded,
        brief=body.brief,
        text=f"Dummy {body.asset_type.replace('_', ' ')} generated {mode} from the brief: \"{body.brief}\".",
        citations=citations,
        created_at=db.now(),
    )
    db.assets[asset.id] = asset
    return asset


@app.get("/projects/{project_id}/assets", response_model=list[Asset])
def list_assets(project_id: str):
    """List all generated assets of a project.

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
    """
    get_project_or_404(project_id)
    return [a for a in db.assets.values() if a.project_id == project_id]


@app.get("/assets/{asset_id}", response_model=Asset)
def get_asset(asset_id: str):
    """Return one generated asset.

    Args:
        asset_id: Id of the asset (path parameter).

    Raises:
        HTTPException: 404 when no asset has this id.
    """
    asset = db.assets.get(asset_id)
    if asset is None:
        raise HTTPException(404, f"Asset '{asset_id}' not found")
    return asset


# ---------- Verification ----------
@app.post("/projects/{project_id}/verify", response_model=VerifyResponse)
def verify(project_id: str, body: VerifyRequest):
    """Check each claim of a text against the project's sources (dummy implementation).

    Splits the text into sentences at "." and marks a sentence as verified when it contains a
    quotation mark; all others are "not_found". No real retrieval is done yet.

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
        body: The text to verify.

    Returns:
        One VerifyItem per sentence, in text order.
    """
    get_project_or_404(project_id)
    # Dummy: split into sentences; mark sentences containing a quote as verified.
    sentences = [s.strip() for s in body.text.replace("\n", " ").split(".") if s.strip()]
    items = [
        VerifyItem(claim=s, status="verified", chunk_id="chk_0002", score=0.94) if '"' in s or "“" in s
        else VerifyItem(claim=s, status="not_found")
        for s in sentences
    ]
    return VerifyResponse(items=items)


# cd server
# uv run fastapi dev server.py
