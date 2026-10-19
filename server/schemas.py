"""Request and response models for the Marketer App API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SourceKind = Literal["document", "video", "audio", "text"]
SourceStatus = Literal["queued", "transcribing", "chunking", "embedding", "ready", "failed"]
AssetType = Literal["blurb", "social_post", "newsletter", "ad_copy", "lead_magnet", "persona"]


# ---------- Health ----------
class ServiceStatus(BaseModel):
    name: str
    ok: bool
    detail: str


class Health(BaseModel):
    ok: bool
    services: list[ServiceStatus]


# ---------- Projects ----------
class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class Project(BaseModel):
    id: str
    name: str
    description: str
    created_at: datetime
    source_count: int = 0
    chunk_count: int = 0
    asset_count: int = 0


# ---------- Sources ----------
class Source(BaseModel):
    id: str
    project_id: str
    filename: str
    kind: SourceKind
    size_bytes: int
    status: SourceStatus
    progress: int = Field(ge=0, le=100)
    chunk_count: int
    created_at: datetime
    error: str | None = None


# ---------- Chunks & search ----------
class ChunkLocation(BaseModel):
    """Where a chunk came from: chapter/page for documents, timestamp for media."""

    chapter: str | None = None
    page: int | None = None
    start_time: str | None = None
    end_time: str | None = None


class Chunk(BaseModel):
    id: str
    source_id: str
    text: str
    location: ChunkLocation
    token_count: int


class ChunkPage(BaseModel):
    items: list[Chunk]
    total: int
    offset: int
    limit: int


class SearchRequest(BaseModel):
    query: str
    k: int = Field(default=5, ge=1, le=50)
    source_ids: list[str] | None = None


class SearchHit(BaseModel):
    chunk: Chunk
    score: float


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]


# ---------- Generation & assets ----------
class GenerateRequest(BaseModel):
    asset_type: AssetType
    brief: str
    grounded: bool = True
    k: int = Field(default=5, ge=1, le=20)


class Citation(BaseModel):
    chunk_id: str
    source_id: str
    location: ChunkLocation
    quote: str
    score: float


class Asset(BaseModel):
    id: str
    project_id: str
    asset_type: AssetType
    grounded: bool
    brief: str
    text: str
    citations: list[Citation]
    created_at: datetime


# ---------- Verification ----------
class VerifyRequest(BaseModel):
    text: str


class VerifyItem(BaseModel):
    claim: str
    status: Literal["verified", "not_found"]
    chunk_id: str | None = None
    score: float | None = None


class VerifyResponse(BaseModel):
    items: list[VerifyItem]
