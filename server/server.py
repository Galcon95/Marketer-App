"""Marketer App API. All endpoints currently return dummy data (see dummy_data.py)."""

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

import dummy_data as db
from schemas import (
    Asset, Chunk, ChunkPage, GenerateRequest, Health, Project, ProjectCreate, SearchHit,
    SearchRequest, SearchResponse, ServiceStatus, Source, SourceKind, VerifyItem,
    VerifyRequest, VerifyResponse,
)

app = FastAPI(title="Marketer App API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Helpers ----------
def get_project_or_404(project_id: str) -> Project:
    project = db.projects.get(project_id)
    if project is None:
        raise HTTPException(404, f"Project '{project_id}' not found")
    return project


def get_source_or_404(source_id: str) -> Source:
    source = db.sources.get(source_id)
    if source is None:
        raise HTTPException(404, f"Source '{source_id}' not found")
    return source


def with_counts(project: Project) -> Project:
    source_ids = {s.id for s in db.sources.values() if s.project_id == project.id}
    return project.model_copy(update={
        "source_count": len(source_ids),
        "chunk_count": sum(1 for c in db.chunks.values() if c.source_id in source_ids),
        "asset_count": sum(1 for a in db.assets.values() if a.project_id == project.id),
    })


def detect_kind(filename: str) -> SourceKind:
    ext = Path(filename).suffix.lower()
    if ext in {".mp4", ".mov", ".mkv", ".webm"}:
        return "video"
    if ext in {".mp3", ".wav", ".m4a"}:
        return "audio"
    if ext in {".txt", ".md"}:
        return "text"
    return "document"


def project_chunks(project_id: str, source_ids: list[str] | None = None) -> list[Chunk]:
    allowed = {s.id for s in db.sources.values() if s.project_id == project_id}
    if source_ids:
        allowed &= set(source_ids)
    return [c for c in db.chunks.values() if c.source_id in allowed]


# ---------- Basic ----------
@app.get("/")
def root():
    return {"message": "Hello, World!"}


@app.get("/test")
def test():
    return {"message": "Hello, Server World!"}


@app.get("/health", response_model=Health)
def health():
    services = [
        ServiceStatus(name="api", ok=True, detail="running"),
        ServiceStatus(name="vector_db", ok=False, detail="dummy · not connected"),
        ServiceStatus(name="llm", ok=False, detail="dummy · not connected"),
    ]
    return Health(ok=services[0].ok, services=services)


# ---------- Projects ----------
@app.post("/projects", response_model=Project, status_code=201)
def create_project(body: ProjectCreate):
    project = Project(id=db.new_id("prj"), name=body.name, description=body.description, created_at=db.now())
    db.projects[project.id] = project
    return project


@app.get("/projects", response_model=list[Project])
def list_projects():
    return [with_counts(p) for p in db.projects.values()]


@app.get("/projects/{project_id}", response_model=Project)
def get_project(project_id: str):
    return with_counts(get_project_or_404(project_id))


# ---------- Sources (content upload & ingestion) ----------
@app.post("/projects/{project_id}/sources", response_model=Source, status_code=202)
async def upload_source(project_id: str, file: UploadFile = File(...)):
    get_project_or_404(project_id)
    content = await file.read()  # dummy: read to get the size, then discard
    source = Source(
        id=db.new_id("src"),
        project_id=project_id,
        filename=file.filename or "upload",
        kind=detect_kind(file.filename or ""),
        size_bytes=len(content),
        status="queued",
        progress=0,
        chunk_count=0,
        created_at=db.now(),
    )
    db.sources[source.id] = source
    return source


@app.get("/projects/{project_id}/sources", response_model=list[Source])
def list_sources(project_id: str):
    get_project_or_404(project_id)
    return [simulate_ingestion(s) for s in db.sources.values() if s.project_id == project_id]


@app.get("/sources/{source_id}", response_model=Source)
def get_source(source_id: str):
    return simulate_ingestion(get_source_or_404(source_id))


def simulate_ingestion(source: Source) -> Source:
    """Dummy progress: the ingestion pipeline advances with elapsed time (~10 s total)."""
    if source.status == "ready":
        return source
    elapsed = (db.now() - source.created_at).total_seconds()
    progress = min(100, int(elapsed * 10))
    stages = ["queued", "transcribing", "chunking", "embedding"] if source.kind in ("video", "audio") \
        else ["queued", "chunking", "embedding"]
    status = "ready" if progress >= 100 else stages[min(len(stages) - 1, progress * len(stages) // 100)]
    return source.model_copy(update={"status": status, "progress": progress,
                                     "chunk_count": 42 if status == "ready" else 0})


@app.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: str):
    get_source_or_404(source_id)
    del db.sources[source_id]
    for chunk_id in [c.id for c in db.chunks.values() if c.source_id == source_id]:
        del db.chunks[chunk_id]


# ---------- Chunks & search (RAG retrieval) ----------
@app.get("/sources/{source_id}/chunks", response_model=ChunkPage)
def list_chunks(source_id: str, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    get_source_or_404(source_id)
    items = [c for c in db.chunks.values() if c.source_id == source_id]
    return ChunkPage(items=items[offset:offset + limit], total=len(items), offset=offset, limit=limit)


@app.post("/projects/{project_id}/search", response_model=SearchResponse)
def search(project_id: str, body: SearchRequest):
    get_project_or_404(project_id)
    candidates = project_chunks(project_id, body.source_ids)[: body.k]
    # Dummy scores: descending from 0.94, no real similarity yet.
    hits = [SearchHit(chunk=c, score=round(0.94 - i * 0.07, 2)) for i, c in enumerate(candidates)]
    return SearchResponse(query=body.query, hits=hits)


# ---------- Generation & assets ----------
@app.post("/projects/{project_id}/generate", response_model=Asset, status_code=201)
def generate(project_id: str, body: GenerateRequest):
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
    get_project_or_404(project_id)
    return [a for a in db.assets.values() if a.project_id == project_id]


@app.get("/assets/{asset_id}", response_model=Asset)
def get_asset(asset_id: str):
    asset = db.assets.get(asset_id)
    if asset is None:
        raise HTTPException(404, f"Asset '{asset_id}' not found")
    return asset


# ---------- Verification ----------
@app.post("/projects/{project_id}/verify", response_model=VerifyResponse)
def verify(project_id: str, body: VerifyRequest):
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
