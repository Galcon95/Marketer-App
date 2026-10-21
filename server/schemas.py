"""Request and response models for the Marketer App API.

Every class here is a Pydantic model. FastAPI uses them to validate incoming JSON bodies
(the *Request / *Create models) and to serialize outgoing responses (all other models).
Class docstrings also appear as schema descriptions in the generated OpenAPI docs (/docs).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# Kind of content a source holds; decides how it will be ingested (parsed vs. transcribed).
SourceKind = Literal["document", "video", "audio", "text"]
# Lifecycle of a source:
# uploaded = file stored on the server, not processed yet; queued … embedding = ingestion running;
# ready = chunks are searchable; failed = ingestion stopped, see Source.error.
SourceStatus = Literal["uploaded", "queued", "transcribing", "chunking", "embedding", "ready", "failed"]
# Kinds of marketing content the generator can produce.
AssetType = Literal["blurb", "social_post", "social_reply", "video_script", "youtube_video", "newsletter",
                    "ad_copy", "lead_magnet", "persona"]
# Writing style options for generated assets (see generation.py for what each one means).
Tone = Literal["neutral", "inspiring", "friendly", "professional", "punchy", "literary"]
Length = Literal["short", "standard", "long"]  # ignored for social posts and replies (the platform decides)
# For social posts, replies and short video scripts.
Platform = Literal["x", "linkedin", "instagram", "facebook", "tiktok", "youtube"]


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
    token_count: int = 0  # LLM tokens (prompt + completion) used by the project's generated assets and book summaries


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
    """Request body for POST /projects/{id}/generate: what marketing asset to write and how.

    For "social_reply", reply_to (the post to answer) is required and the brief is an optional
    angle; for all other types the brief is required.
    """

    asset_type: AssetType  # kind of asset to produce
    brief: str = ""  # what to write about: topic, angle, message (for replies: optional angle)
    grounded: bool = True  # True = RAG over project chunks with citations; False = zero-shot LLM
    k: int = Field(default=5, ge=1, le=20)  # number of chunks to retrieve as context (1-20)
    tone: Tone = "neutral"
    length: Length = "standard"
    audience: str = ""  # optional target audience, e.g. "urban planners"
    platform: Platform = "x"  # used for social posts and replies
    reply_to: str = ""  # the post to reply to (social_reply only)
    humanize: int = Field(default=60, ge=0, le=100)  # how human it should sound: 0 = polished marketing, 100 = casual person
    source_ids: list[str] | None = None  # the book(s) to work on; None = all books of the project

    @model_validator(mode="after")
    def _check_inputs(self) -> "GenerateRequest":
        """Require the post for replies and a brief for everything else."""
        if self.asset_type == "social_reply" and not self.reply_to.strip():
            raise ValueError("Paste the post you want to reply to.")
        if self.asset_type != "social_reply" and not self.brief.strip():
            raise ValueError("Write a brief.")
        return self


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
    brief: str  # the brief it was generated from (for replies: the optional angle)
    text: str  # the generated content, with [n] citation markers (the GUI copies it without them)
    citations: list[Citation]  # supporting chunks; empty when not grounded
    created_at: datetime  # generation time in UTC
    tokens: int = 0  # LLM tokens (prompt + completion) used to generate it
    tone: Tone = "neutral"
    length: Length = "standard"
    audience: str = ""
    platform: Platform | None = None  # set for social posts and replies
    reply_to: str = ""  # the post it replies to (social_reply only)
    search_query: str = ""  # what was searched in the books: the brief, or for replies the planned query
    humanize: int = 60  # the "how human" setting it was generated with (0-100)
    source_ids: list[str] = []  # the book(s) it was generated for; empty = all books of the project
    ai_tells: list[str] = []  # AI-typical phrases still found in the final text (empty = none)
    edited: bool = False  # True once the user changed the text
    campaign_id: str = ""  # set for assets made together by POST /campaigns (personas, posts, blurb)
    persona: str = ""  # campaign posts: name of the persona the post is written for
    angle: str = ""  # campaign posts: "hook", "teaser", "question", "behind the scenes" or "call to action"


class CampaignRequest(BaseModel):
    """Request body for POST /projects/{id}/campaigns: a short book brief for a zero-shot campaign kit.

    The model sees only this brief (no excerpts). The GUI pre-fills it from the library (title and
    author from the file name, themes and hook from the book summary); the author can edit everything.
    """

    title: str = Field(min_length=1)  # book title
    author: str = ""  # author or pen name
    genre: str = ""  # genre / subgenre, e.g. "cozy mystery"
    themes: list[str] = []  # key themes to build on
    premise: str = Field(min_length=1)  # hook / premise: what the book is about, in a few sentences
    comparables: str = ""  # "for fans of ...": comparable authors or books
    audience: str = ""  # optional audience focus for the personas, e.g. "book clubs"
    humanize: int = Field(default=60, ge=0, le=100)  # how human it should sound (see GenerateRequest)
    source_id: str | None = None  # the book in the library, if it is one (links the assets to it)


class CampaignResponse(BaseModel):
    """Response of POST /projects/{id}/campaigns: the stored assets of one campaign kit."""

    campaign_id: str  # shared by all assets of the kit, e.g. "cmp_1a2b3c4d"
    personas: list[Asset]  # 3 reader personas
    posts: list[Asset]  # 5 social posts, each written for one persona
    blurb: Asset  # back-cover / store description
    tokens: int  # LLM tokens used by the whole kit


class AssetUpdate(BaseModel):
    """Request body for PATCH /assets/{id}: the user's edited text."""

    text: str = Field(min_length=1)


# ---------- Questions & answers ----------
class AskRequest(BaseModel):
    """Request body for POST /projects/{id}/ask: a question about the project's books."""

    question: str  # natural-language question
    k: int = Field(default=6, ge=1, le=20)  # number of passages to retrieve as context (1-20)
    source_ids: list[str] | None = None  # restrict to these sources; None = all sources


class AskResponse(BaseModel):
    """Response of POST /projects/{id}/ask: an answer written from the books, with its evidence."""

    question: str  # echo of the question
    answer: str  # answer based only on the retrieved passages, with [n] citation markers
    citations: list[Citation]  # the passages cited in the answer, numbered like the markers
    passages: list[SearchHit]  # all retrieved passages, best first (what the answer could draw on)
    model: str  # chat model that wrote the answer
    tokens: int  # LLM tokens (prompt + completion) used


# ---------- Usage & costs ----------
class UsageRecord(BaseModel):
    """One logged model call (chat or embedding) with its tokens and costs in USD (see usage.py)."""

    timestamp: datetime  # when the call finished (UTC)
    operation: str  # what it was for, e.g. "generate_blurb/generate", "ask/embed_query", "embed_chunks"
    kind: Literal["chat", "embedding"]
    model: str
    input_tokens: int  # tokens sent to the model ("upload")
    output_tokens: int  # tokens received from the model ("download"); 0 for embeddings
    input_cost: float  # USD for the input tokens
    output_cost: float  # USD for the output tokens
    cost: float  # USD for the whole call
    cost_source: Literal["provider", "estimate"]  # provider = exact cost reported by OpenRouter; estimate = price list
    project_id: str | None = None
    source_id: str | None = None


class UsageTotals(BaseModel):
    """Sums over a set of model calls."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    input_cost: float = 0.0  # USD
    output_cost: float = 0.0  # USD
    cost: float = 0.0  # USD, all costs


class UsageReport(BaseModel):
    """Response of GET /usage: totals so far, totals per operation, and the latest calls."""

    totals: UsageTotals
    by_operation: dict[str, UsageTotals]  # sorted by cost, highest first
    recent: list[UsageRecord]  # newest first


# ---------- Book summaries ----------
class ChapterSummary(BaseModel):
    """Short summary of one chapter (or section) of a book."""

    chapter: str | None  # chapter title from the table of contents; None for text before the first chapter
    first_page: int | None  # page where the chapter starts
    last_page: int | None  # page where the chapter ends
    summary: str  # 2-4 sentences


class BookSummary(BaseModel):
    """Summary of a whole book, made by map-reduce over its chapters (see summary.py).

    Saved next to the book (.summary.json) and loaded on startup, so it is created only once; kept
    when the book is re-indexed (same content), removed when the book is deleted.
    """

    source_id: str  # the book (source) it summarizes
    summary: str  # what the book is about, in about two paragraphs
    themes: list[str]  # 4-6 key themes as short phrases
    chapters: list[ChapterSummary]  # content chapters in reading order (front/back matter skipped)
    model: str  # chat model that wrote it
    tokens: int  # LLM tokens (prompt + completion) used to create it
    created_at: datetime  # creation time in UTC


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
