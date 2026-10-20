"""Request and response models for the Marketer App API.

Every class here is a Pydantic model. FastAPI uses them to validate incoming JSON bodies
(the *Request / *Create models) and to serialize outgoing responses (all other models).
Class docstrings also appear as schema descriptions in the generated OpenAPI docs (/docs).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Kind of content a source holds; decides how it will be ingested (parsed vs. transcribed).
SourceKind = Literal["document", "video", "audio", "text"]
# Lifecycle of a source:
# uploaded = file stored on the server, not processed yet; queued … embedding = ingestion running;
# ready = chunks are searchable; failed = ingestion stopped, see Source.error.
SourceStatus = Literal["uploaded", "queued", "transcribing", "chunking", "embedding", "ready", "failed"]
# Kinds of marketing content the generator can produce.
AssetType = Literal["blurb", "social_post", "newsletter", "ad_copy", "lead_magnet", "persona"]


# ---------- Health ----------
class ServiceStatus(BaseModel):
    """Status of one backend dependency (API, vector database, LLM) as shown on the health check."""

    name: str  # service identifier, e.g. "api", "vector_db", "llm"
    ok: bool  # True when the service is reachable and working
    detail: str  # short human-readable explanation, e.g. "running" or "not connected"


class Health(BaseModel):
    """Response of GET /health: overall status plus the status of each individual service."""

    ok: bool  # overall health of the API itself
    services: list[ServiceStatus]  # one entry per dependency


# ---------- Projects ----------
class ProjectCreate(BaseModel):
    """Request body for POST /projects: the user-editable fields of a new project."""

    name: str  # display name of the project / campaign
    description: str = ""  # optional free-text description


class Project(BaseModel):
    """A project (marketing campaign) that groups sources, their chunks and the generated assets.

    The *_count fields are not stored; they are computed on read (see server.with_counts).
    """

    id: str  # unique id, e.g. "prj_1a2b3c4d"
    name: str
    description: str
    created_at: datetime  # creation time in UTC
    source_count: int = 0  # number of uploaded sources in the project
    chunk_count: int = 0  # number of chunks across all sources of the project
    asset_count: int = 0  # number of generated assets in the project


# ---------- Sources ----------
class Source(BaseModel):
    """One uploaded file (book, video, audio, text) inside a project, plus its ingestion state."""

    id: str  # unique id, e.g. "src_1a2b3c4d"
    project_id: str  # project the source belongs to
    filename: str  # sanitized original file name (see storage.safe_filename)
    kind: SourceKind  # content kind derived from the file extension
    size_bytes: int  # file size on disk
    status: SourceStatus  # current ingestion step
    progress: int = Field(ge=0, le=100)  # progress of the current step in percent (0-100)
    chunk_count: int  # number of chunks produced from this source so far
    created_at: datetime  # upload time in UTC
    error: str | None = None  # error message when status == "failed", otherwise None


# ---------- Chunks & search ----------
class ChunkLocation(BaseModel):
    """Where a chunk came from: chapter/page for documents, timestamp for media.

    Only the fields that apply to the source kind are set; the rest stay None.
    """

    chapter: str | None = None  # chapter identifier (documents)
    page: int | None = None  # page number (documents)
    start_time: str | None = None  # start timestamp "HH:MM:SS" (video/audio)
    end_time: str | None = None  # end timestamp "HH:MM:SS" (video/audio)


class Chunk(BaseModel):
    """A small piece of text cut from a source; the unit that is embedded and retrieved by RAG search."""

    id: str  # unique id, e.g. "chk_0001"
    source_id: str  # source the chunk was cut from
    text: str  # the chunk text (or transcript excerpt for media)
    location: ChunkLocation  # position of the chunk inside its source
    token_count: int  # size of the text in LLM tokens


class ChunkPage(BaseModel):
    """One page of chunks returned by GET /sources/{id}/chunks (offset/limit pagination)."""

    items: list[Chunk]  # chunks on this page
    total: int  # total number of chunks of the source
    offset: int  # index of the first item in this page
    limit: int  # maximum number of items per page


class SearchRequest(BaseModel):
    """Request body for POST /projects/{id}/search: a semantic search over the project's chunks."""

    query: str  # natural-language search text
    k: int = Field(default=5, ge=1, le=50)  # number of hits to return (1-50)
    source_ids: list[str] | None = None  # restrict search to these sources; None = all sources


class SearchHit(BaseModel):
    """One search result: a matching chunk and its similarity score."""

    chunk: Chunk
    score: float  # similarity to the query, higher is better (0-1)


class SearchResponse(BaseModel):
    """Response of POST /projects/{id}/search: the original query and its ranked hits."""

    query: str  # echo of the search query
    hits: list[SearchHit]  # results sorted by score, best first


# ---------- Generation & assets ----------
class GenerateRequest(BaseModel):
    """Request body for POST /projects/{id}/generate: what marketing asset to write and how."""

    asset_type: AssetType  # kind of asset to produce
    brief: str  # user instructions for the generator (tone, audience, angle, ...)
    grounded: bool = True  # True = RAG over project chunks with citations; False = zero-shot LLM
    k: int = Field(default=5, ge=1, le=20)  # number of chunks to retrieve as context (1-20)


class Citation(BaseModel):
    """A reference from a generated asset back to the source chunk that supports it."""

    chunk_id: str  # cited chunk
    source_id: str  # source of the cited chunk
    location: ChunkLocation  # where in the source the quote is found
    quote: str  # excerpt of the chunk text shown to the user
    score: float  # retrieval similarity score of the chunk


class Asset(BaseModel):
    """A generated piece of marketing content (blurb, post, newsletter, ...) stored in a project."""

    id: str  # unique id, e.g. "ast_1a2b3c4d"
    project_id: str  # project the asset belongs to
    asset_type: AssetType  # kind of asset
    grounded: bool  # whether it was generated with RAG context
    brief: str  # the brief it was generated from
    text: str  # the generated content
    citations: list[Citation]  # supporting chunks; empty when not grounded
    created_at: datetime  # generation time in UTC


# ---------- Verification ----------
class VerifyRequest(BaseModel):
    """Request body for POST /projects/{id}/verify: text whose claims should be checked against the sources."""

    text: str  # text to fact-check, e.g. a generated asset


class VerifyItem(BaseModel):
    """Verification result for one claim (sentence) of the checked text."""

    claim: str  # the sentence that was checked
    status: Literal["verified", "not_found"]  # whether a supporting chunk was found
    chunk_id: str | None = None  # supporting chunk when verified, otherwise None
    score: float | None = None  # similarity to the supporting chunk when verified, otherwise None


class VerifyResponse(BaseModel):
    """Response of POST /projects/{id}/verify: one result per claim, in text order."""

    items: list[VerifyItem]
