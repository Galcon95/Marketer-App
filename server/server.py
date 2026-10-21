"""Marketer App API. Uploads are stored (storage.py), processed into chunks and embedded into the
Chroma vector store (ingestion.py, vectorstore.py, all LangChain); search, citations and verification
use real similarity search; assets (generation.py), answers to questions (qa.py) and book summaries
(summary.py) and zero-shot campaign kits (campaign.py) are written by an LLM via LangGraph graphs,
traced in LangSmith when enabled."""

import re
from datetime import timedelta

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

import campaign
import dummy_data as db
import generation
import ingestion
import storage
import qa
import summary
import usage
import vectorstore
from schemas import (
    AskRequest, AskResponse, Asset, AssetUpdate, BookSummary, CampaignRequest, CampaignResponse, Chunk, ChunkPage, GenerateRequest, Health, Project, ProjectCreate, SearchHit,
    SearchRequest, SearchResponse, ServiceStatus, Source, UsageReport, VerifyItem,
    VerifyRequest, VerifyResponse,
)

# Restore uploaded sources (with their chunks) and generated assets from disk, so they survive
# server restarts.
ingestion.restore_sources()
db.assets.update(storage.load_assets())
usage.load()  # totals of all model calls so far (usage.jsonl)

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
    """Return a copy of a project with source_count, chunk_count, asset_count and token_count filled in.

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
        "token_count": sum(a.tokens for a in db.assets.values() if a.project_id == project.id)
                       + sum(s.tokens for sid, s in db.summaries.items() if sid in source_ids),
    })


# Minimum similarity for a claim to count as verified by a source chunk (cosine similarity, 0-1).
VERIFY_MIN_SCORE = 0.5


def retrieve(project_id: str, query: str, k: int, source_ids: list[str] | None = None,
             operation: str = "search") -> list[tuple[Chunk, float]]:
    """Find the project's chunks most similar to a query (vector search in Chroma).

    Wraps generation.retrieve_chunks and turns vector store errors into HTTP errors.

    Args:
        project_id: Project to search in.
        query: Natural-language query.
        k: Maximum number of results.
        source_ids: Optional filter: only search these sources.
        operation: What the search is for, for the usage log (e.g. "search", "verify").

    Returns:
        (chunk, similarity) pairs, best first.

    Raises:
        HTTPException: 503 if no embedding API key is configured, 502 if the search fails.
    """
    try:
        return generation.retrieve_chunks(project_id, query, k, source_ids, operation=operation)
    except vectorstore.VectorStoreError as e:
        raise HTTPException(503 if not vectorstore.is_configured() else 502, str(e)) from e


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

    The vector database is reported with its vector count and embedding model, the LLM with its
    model and whether LangSmith tracing is on (both down if no API key is set). Overall `ok`
    reflects only the API itself.
    """
    vector_ok, vector_detail = vectorstore.health()
    llm_ok, llm_detail = generation.health()
    services = [
        ServiceStatus(name="api", ok=True, detail="running"),
        ServiceStatus(name="vector_db", ok=vector_ok, detail=vector_detail),
        ServiceStatus(name="llm", ok=llm_ok, detail=llm_detail),
    ]
    return Health(ok=services[0].ok, services=services)


@app.get("/usage", response_model=UsageReport)
def get_usage(limit: int = Query(50, ge=1, le=1000)):
    """Tokens and costs of all model calls so far (see usage.py).

    Args:
        limit: Number of latest calls to include (query parameter, 1-1000).

    Returns:
        Totals (input/output tokens and costs, all costs), totals per operation, latest calls.
    """
    return usage.report(limit)


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


@app.post("/sources/{source_id}/ingest", response_model=Source, status_code=202)
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
    """Delete a source with its stored files, chunks and vectors (also while it is processing).

    Args:
        source_id: Id of the source (path parameter). 404 if unknown.
    """
    source = get_source_or_404(source_id)
    # Remove the record first, so a running ingestion sees the deletion and stops writing.
    db.sources.pop(source_id, None)
    ingestion.delete_source_data(source)
    storage.delete_source_files(source.project_id, source_id)


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


@app.get("/sources/{source_id}/file", response_class=FileResponse)
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


@app.get("/sources/{source_id}/cover", response_class=FileResponse)
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


@app.get("/sources/{source_id}/summary", response_model=BookSummary)
def get_summary(source_id: str):
    """Return the saved summary of a book.

    Args:
        source_id: Id of the source (path parameter). 404 if unknown.

    Raises:
        HTTPException: 404 if the source is unknown or has no summary yet.
    """
    get_source_or_404(source_id)
    found = db.summaries.get(source_id)
    if found is None:
        raise HTTPException(404, "No summary yet")
    return found


@app.post("/sources/{source_id}/summary", response_model=BookSummary, status_code=201)
def create_summary(source_id: str):
    """Create (or recreate) the summary of a processed book: chapter summaries + book overview.

    Runs the LangGraph map-reduce in summary.py over all of the book's chunks, which takes some
    seconds (one model call per chapter, in parallel, plus one to combine). The result is saved and
    then used as background in grounded generation.

    Args:
        source_id: Id of the source (path parameter). 404 if unknown.

    Returns:
        The new summary.

    Raises:
        HTTPException: 409 if the book is not processed ("ready"); 503 if no API key is configured;
            502 if a model call fails.
    """
    source = get_source_or_404(source_id)
    if source.status != "ready":
        raise HTTPException(409, f"'{source.filename}' must be processed (status ready) before it can be summarized")
    try:
        return summary.summarize_source(source)
    except generation.GenerationError as e:
        raise HTTPException(e.status_code, str(e)) from e
    except OSError as e:
        raise HTTPException(500, "The summary was created but could not be saved") from e


@app.post("/projects/{project_id}/ask", response_model=AskResponse)
def ask(project_id: str, body: AskRequest):
    """Answer a question from the project's books, NotebookLM-style.

    Runs the LangGraph in qa.py: the k passages most similar to the question are retrieved, and the
    LLM writes an answer from those passages only (plus the book summary as background), citing
    them as [n]. Says so when the passages do not answer the question.

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
        body: The question, number of passages k and optional source filter.

    Returns:
        The answer with its cited passages, all retrieved passages and token usage.

    Raises:
        HTTPException: 409 if there is nothing to search; 503 if no API key is configured;
            502 if retrieval or the model call fails.
    """
    get_project_or_404(project_id)
    try:
        return qa.answer_question(project_id, body.question, body.k, body.source_ids)
    except generation.GenerationError as e:
        raise HTTPException(e.status_code, str(e)) from e


@app.post("/projects/{project_id}/search", response_model=SearchResponse)
def search(project_id: str, body: SearchRequest):
    """Find the passages of a project's sources that best match a query (semantic vector search).

    The query is embedded and compared with the chunk vectors in Chroma; scores are cosine
    similarities (about 0-1, higher is better).

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
        body: Query text, number of hits k and optional source filter.

    Returns:
        The query and up to k hits, best first.

    Raises:
        HTTPException: 503 if no embedding API key is configured, 502 if the search fails.
    """
    get_project_or_404(project_id)
    hits = [SearchHit(chunk=c, score=score) for c, score in retrieve(project_id, body.query, body.k, body.source_ids)]
    return SearchResponse(query=body.query, hits=hits)


# ---------- Generation & assets ----------
@app.post("/projects/{project_id}/generate", response_model=Asset, status_code=201)
def generate(project_id: str, body: GenerateRequest):
    """Generate a marketing asset from a brief with the LLM and store it in the project.

    Runs the LangGraph in generation.py. Grounded (RAG): the brief retrieves the k most similar
    chunks, which go into the prompt as numbered excerpts; the model cites them, and the cited ones
    become the asset's citations. Zero-shot: the model writes from the brief alone.

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
        body: Asset type, brief, grounded flag and number of context chunks k.

    Returns:
        The newly created Asset, also saved to disk (storage.write_asset).

    Raises:
        HTTPException: 503 if no API key is configured; 502 if retrieval or the model call fails.
    """
    get_project_or_404(project_id)
    try:
        result = generation.generate_asset(project_id, body)
    except generation.GenerationError as e:
        raise HTTPException(e.status_code, str(e)) from e
    asset = Asset(
        id=db.new_id("ast"),
        project_id=project_id,
        asset_type=body.asset_type,
        grounded=body.grounded,
        brief=body.brief,
        text=result["text"],
        citations=result.get("citations", []),
        created_at=db.now(),
        tokens=result.get("tokens", 0),
        tone=body.tone,
        length=body.length,
        audience=body.audience,
        platform=body.platform if body.asset_type in ("social_post", "social_reply", "video_script") else None,
        source_ids=body.source_ids or [],
        reply_to=body.reply_to,
        search_query=result.get("query", ""),
        humanize=body.humanize,
        ai_tells=result.get("ai_tells", []),
    )
    try:
        storage.write_asset(asset)
    except OSError as e:
        raise HTTPException(500, "The asset was generated but could not be saved") from e
    db.assets[asset.id] = asset
    return asset


@app.post("/projects/{project_id}/campaigns", response_model=CampaignResponse, status_code=201)
def create_campaign(project_id: str, body: CampaignRequest):
    """Generate a zero-shot campaign kit from a book brief: 3 personas, 5 social posts, 1 blurb.

    Runs the LangGraph in campaign.py (personas first, then posts and blurb aimed at them). Each
    piece is stored as an ordinary Asset with the same campaign_id, so it can be copied, edited and
    deleted like any other asset. With a source_id, the assets belong to that book.

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
        body: The book brief.

    Returns:
        The kit's stored assets and the tokens it used.

    Raises:
        HTTPException: 404 if the project or the given book is unknown; 503 if no API key is
            configured; 502 if a model call fails; 500 if the assets cannot be saved.
    """
    get_project_or_404(project_id)
    if body.source_id:
        get_source_or_404(body.source_id)
    try:
        result = campaign.generate_campaign(body)
    except generation.GenerationError as e:
        raise HTTPException(e.status_code, str(e)) from e

    campaign_id = db.new_id("cmp")
    brief = campaign.format_brief(body)
    created = db.now()
    order = iter(range(9))  # 1 µs apart, so the kit keeps its order when the assets are reloaded (sorted by time)

    def make(asset_type, text: str, tokens: int, **extra) -> Asset:
        """One asset of the kit with the fields all pieces share."""
        return Asset(id=db.new_id("ast"), project_id=project_id, asset_type=asset_type, grounded=False, brief=brief,
                     text=text, citations=[], created_at=created + timedelta(microseconds=next(order)), tokens=tokens, audience=body.audience,
                     humanize=body.humanize, source_ids=[body.source_id] if body.source_id else [],
                     campaign_id=campaign_id, **extra)

    # Each step's tokens go to its first asset, so the project's token count still adds up.
    personas = [make("persona", campaign.format_persona(p), result["persona_tokens"] if i == 0 else 0)
                for i, p in enumerate(result["personas"])]
    posts = [make("social_post", piece["text"], piece["tokens"] + (result["posts_tokens"] if i == 0 else 0),
                  platform=post.platform, persona=post.persona, angle=post.angle, ai_tells=piece["ai_tells"])
             for i, (post, piece) in enumerate(zip(result["posts"], result["polished_posts"]))]
    piece = result["polished_blurb"]
    blurb = make("blurb", piece["text"], piece["tokens"] + result["blurb_tokens"], ai_tells=piece["ai_tells"])

    try:
        for asset in [*personas, *posts, blurb]:
            storage.write_asset(asset)
            db.assets[asset.id] = asset
    except OSError as e:
        raise HTTPException(500, "The campaign was generated but could not be saved") from e
    return CampaignResponse(campaign_id=campaign_id, personas=personas, posts=posts, blurb=blurb,
                            tokens=result.get("tokens", 0))


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


@app.patch("/assets/{asset_id}", response_model=Asset)
def update_asset(asset_id: str, body: AssetUpdate):
    """Replace the text of a generated asset with the user's edited version (citations are kept).

    Args:
        asset_id: Id of the asset (path parameter).
        body: The new text.

    Raises:
        HTTPException: 404 when no asset has this id; 500 if it cannot be saved.
    """
    asset = db.assets.get(asset_id)
    if asset is None:
        raise HTTPException(404, f"Asset '{asset_id}' not found")
    asset = asset.model_copy(update={"text": body.text, "edited": True})
    try:
        storage.write_asset(asset)
    except OSError as e:
        raise HTTPException(500, "The edited asset could not be saved") from e
    db.assets[asset_id] = asset
    return asset


@app.delete("/assets/{asset_id}", status_code=204)
def delete_asset(asset_id: str):
    """Delete a generated asset (from memory and disk).

    Args:
        asset_id: Id of the asset (path parameter).

    Raises:
        HTTPException: 404 when no asset has this id.
    """
    asset = db.assets.pop(asset_id, None)
    if asset is None:
        raise HTTPException(404, f"Asset '{asset_id}' not found")
    storage.delete_asset(asset)


# ---------- Verification ----------
@app.post("/projects/{project_id}/verify", response_model=VerifyResponse)
def verify(project_id: str, body: VerifyRequest):
    """Check each claim (sentence) of a text against the project's sources.

    Splits the text into sentences and searches the best-matching chunk for each one. A sentence
    counts as verified when that chunk's similarity reaches VERIFY_MIN_SCORE. This finds claims that
    are backed by a similar passage; it does not judge whether the claim is logically entailed.

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
        body: The text to verify.

    Returns:
        One VerifyItem per sentence, in text order.

    Raises:
        HTTPException: 503 if no embedding API key is configured, 502 if the search fails.
    """
    get_project_or_404(project_id)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", body.text.replace("\n", " ")) if s.strip()]
    items = []
    for sentence in sentences:
        best = retrieve(project_id, sentence, k=1, operation="verify")
        if best and best[0][1] >= VERIFY_MIN_SCORE:
            items.append(VerifyItem(claim=sentence, status="verified", chunk_id=best[0][0].id, score=best[0][1]))
        else:
            items.append(VerifyItem(claim=sentence, status="not_found"))
    return VerifyResponse(items=items)


# cd server
# uv run fastapi dev server.py
