"""Request and response models for the Marketer App API.

Every class here is a Pydantic model. FastAPI uses them to validate incoming JSON bodies
(the *Request / *Create models) and to serialize outgoing responses (all other models).
Class docstrings also appear as schema descriptions in the generated OpenAPI docs (/docs).
"""

import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

# Kind of content a source holds; decides how it will be ingested (parsed vs. transcribed).
SourceKind = Literal["document", "video", "audio", "text"]
# Lifecycle of a source:
# uploaded = file stored on the server, not processed yet; queued … embedding = ingestion running;
# ready = chunks are searchable; failed = ingestion stopped, see Source.error.
SourceStatus = Literal["uploaded", "queued", "transcribing", "chunking", "embedding", "ready", "failed"]
# Kinds of marketing content the generator can produce.
AssetType = Literal["blurb", "social_post", "social_reply", "video_script", "youtube_video", "newsletter",
                    "ad_copy", "lead_magnet", "persona", "reader_question"]
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
class Project(BaseModel):
    """A project (a client, shown as "Current client" in the GUI) that groups sources, their chunks and the generated
    assets. Each project belongs to one signed-in user (owner_id); every user has exactly one (accounts.py).

    The *_count fields are not stored; they are computed on read (see projects.with_counts).
    """

    id: str  # unique id, e.g. "prj_1a2b3c4d"
    name: str
    description: str
    created_at: datetime  # creation time in UTC
    owner_id: str = ""  # Supabase user id of the owner; "" = nobody yet (the default project before it is claimed)
    source_count: int = 0  # number of uploaded sources in the project
    chunk_count: int = 0  # number of chunks across all sources of the project
    asset_count: int = 0  # number of generated assets in the project
    token_count: int = 0  # LLM tokens (prompt + completion) used by the project's generated assets and book summaries


class Me(BaseModel):
    """Response of GET /me: the signed-in user, their project (client) and whether they are the app's admin."""

    user_id: str  # Supabase user id
    email: str
    admin: bool  # may see the app-wide usage and costs and use the MCP console (DEFAULT_CLIENT_OWNER)
    project: Project  # the user's own project, with counts


class ApiKey(BaseModel):
    """A personal API key for the MCP servers (api_keys.py), as saved: never the key itself, only its hash."""

    id: str  # "key_..."; used to revoke it
    user_id: str  # Supabase user id of the owner
    email: str  # the owner's email (the MCP servers act as this user, like a signed-in request)
    name: str  # what it is for, e.g. "Claude Desktop"
    shown: str  # the key's first characters, e.g. "mk_AbC123x7", so the user can tell keys apart
    key_hash: str  # SHA-256 of the key (hex)
    created_at: datetime
    last_used_at: datetime | None = None  # updated at most every few minutes


class ApiKeyInfo(BaseModel):
    """One of the user's API keys as the app shows it (GET /api-keys): without the key and without its hash."""

    id: str
    name: str
    shown: str  # the key's first characters, e.g. "mk_AbC123x7"
    created_at: datetime
    last_used_at: datetime | None = None


class ApiKeyCreate(BaseModel):
    """Request body of POST /api-keys."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]  # e.g. "Claude Desktop"


class ApiKeyCreated(ApiKeyInfo):
    """Response of POST /api-keys: the new key itself, shown this one time only."""

    key: str


# ---------- Sources ----------
class Source(BaseModel):
    """One uploaded file (book, video, audio, text) inside a project, plus its ingestion state."""

    id: str  # unique id, e.g. "src_1a2b3c4d"
    project_id: str  # project the source belongs to
    filename: str  # sanitized original file name (see storage.safe_filename)
    kind: SourceKind  # content kind derived from the file extension
    size_bytes: int  # size of the uploaded file
    status: SourceStatus  # current ingestion step
    progress: int = Field(ge=0, le=100)  # progress of the current step in percent (0-100)
    chunk_count: int  # number of chunks produced from this source so far
    created_at: datetime  # upload time in UTC
    error: str | None = None  # error message when status == "failed", otherwise None
    author: str = ""  # from the PDF's metadata (author field, or "..., by Name" in its title); "" if unknown
    sha256: str = ""  # checksum of the file's content; the same file cannot be uploaded twice into a project


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


class SourceDeletion(BaseModel):
    """What deleting a book removes besides its file, chunks, vectors and summary: the generated assets made only
    from this book (incl. its campaign kits) and the chats that only used its passages. Returned by the preview
    (GET /sources/{id}/deletion, for the confirmation) and by DELETE /sources/{id} (what was removed)."""

    source_id: str
    name: str  # readable book name, e.g. "Successful Stock Speculation — J. J. Butler"
    assets: int  # generated assets made only from this book
    conversations: int  # chats whose passages all come from this book
    discussions: int = 0  # discussion analyses made for this book (Market Intelligence)


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
    model: str | None = None  # chat model that wrote it; None for assets saved before this was recorded
    prompt_version: str | None = None  # prompts that wrote it, e.g. "generation@3f9a1c2e" (core/prompts.py); None = older
    persona: str = ""  # campaign posts: name of the persona the post is written for
    angle: str = ""  # campaign posts: "hook", "teaser", "question", "behind the scenes" or "call to action"
    published_id: str = ""  # id of the post it was published as on the author's Facebook Page; "" = not published
    published_url: str = ""  # link to that post
    published_at: datetime | None = None


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

    question: str = Field(min_length=1, max_length=4000)  # question or chat message, may contain a pasted post (cleaned again by guard)
    k: int = Field(default=6, ge=1, le=20)  # number of passages to retrieve as context (1-20)
    source_ids: list[str] | None = None  # restrict to these sources; None = all sources
    conversation_id: str | None = None  # continue this conversation; None = start a new one


class AskResponse(BaseModel):
    """Response of POST /projects/{id}/ask: an answer written from the books, with its evidence."""

    question: str  # echo of the question
    search_query: str  # what was searched: the question, or its standalone rewrite for a follow-up
    filters: str = ""  # book/chapter/page filters taken from the question (structured retrieval); "" = none
    answer: str  # answer based only on the retrieved passages, with [n] citation markers
    citations: list[Citation]  # the passages cited in the answer, numbered like the markers
    passages: list[SearchHit]  # all retrieved passages, best first (what the answer could draw on)
    model: str  # chat model that wrote the answer
    prompt_version: str | None = None  # prompts that wrote it, e.g. "qa@3f9a1c2e" (core/prompts.py)
    tokens: int  # LLM tokens (prompt + completion) used
    conversation_id: str | None = None  # the conversation this turn belongs to (None for stateless callers like MCP)
    tool_calls: list["ToolCallRecord"] = []  # tools the model called for this answer (chat only), in call order


class ToolCallRecord(BaseModel):
    """One tool call the chat model made (rag/chat_tools.py), with its result."""

    name: str  # e.g. "check_platform_fit"
    arguments: dict[str, Any]  # as the model wrote them
    ok: bool  # False if the arguments were invalid or the tool failed
    result: Any = None  # the tool's result (JSON), or the error message
    duration_ms: int


class ChatTurn(AskResponse):
    """One question and its answer inside a conversation."""

    created_at: datetime


class Conversation(BaseModel):
    """A chat with the books ("Ask your book"): its turns, oldest first. Saved in the database (table conversations)."""

    id: str  # unique id, e.g. "cnv_1a2b3c4d"
    project_id: str
    title: str  # the first question, shortened
    created_at: datetime
    updated_at: datetime  # time of the last turn
    turns: list[ChatTurn] = []


class ConversationInfo(BaseModel):
    """A conversation without its turns, for the list of past chats."""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    turn_count: int


# ---------- Discussions (Market Intelligence: Discussion Relevance Agent) ----------
# Where a discussion was found. The social platforms match Platform, so the draft reply can be checked against
# their rules (core/platforms.py); "reddit", "forum" and "other" have no fixed rules.
# Prompt-injection risk of someone else's text (core/guard.scan_third_party; the same values as guard.InjectionRisk).
InjectionRisk = Literal["none", "low", "high"]
DiscussionPlatform = Literal["reddit", "linkedin", "youtube", "x", "facebook", "instagram", "tiktok", "forum", "other"]
# What the agent recommends: write a reply, ask the author for more of the discussion, or leave it.
Recommendation = Literal["contribute", "more_context", "skip"]


class DiscussionRequest(BaseModel):
    """Request body for POST /projects/{id}/discussions: a discussion from another platform to analyse for one book.

    The author copies a post (and, if useful, some replies) from Reddit, LinkedIn, YouTube or a forum and pastes
    it here. The text is third-party content: it is checked by the guard and given to the model as data only.
    """

    source_id: str = Field(min_length=1)  # the book to contribute from
    discussion: str = Field(min_length=1, max_length=8000)  # the pasted post and replies (cleaned again by guard)
    url: str = Field(default="", max_length=2000)  # where the discussion is, so the author can go back and post
    platform: DiscussionPlatform = "forum"
    angle: str = Field(default="", max_length=1000)  # optional: what the author would like to bring in
    # How human the reply should sound (core/style.py): 0 = polished, 100 = casual person. From 60 on, AI clichés found
    # in the draft are rewritten once. Default 80: a person in a discussion, not marketing copy.
    humanize: int = Field(default=80, ge=0, le=100)
    tone: Tone = "neutral"  # the reply's tone, as in the generator (core/style.TONES)
    # A comment on the author's own Facebook Page (social/facebook.py): the agent answers it as the author ("own Page"
    # mode: naming the book is fine) and the reply can be posted under it as the Page. "" = a discussion elsewhere.
    facebook_comment_id: str = Field(default="", pattern=r"^(\d+(_\d+)?)?$")

    @model_validator(mode="after")
    def _check_url(self) -> "DiscussionRequest":
        """Accept an empty URL or a web address (http or https), nothing else (no javascript: links in the GUI).
        A comment on the author's Facebook Page is always on Facebook."""
        self.url = self.url.strip()
        if self.url and not self.url.lower().startswith(("http://", "https://")):
            raise ValueError("The URL must start with http:// or https://.")
        if self.facebook_comment_id:
            self.platform = "facebook"
        return self


class BookMention(BaseModel):
    """The agent's advice on naming the book in the reply; the author decides."""

    suggest: bool  # True = mentioning the book would help the discussion (not just advertise it)
    reason: str  # why, or why not


class DiscussionAnalysis(BaseModel):
    """The Discussion Relevance Agent's result for one discussion, saved for the author to review and edit."""

    id: str  # unique id, e.g. "dsc_1a2b3c4d"
    project_id: str
    source_id: str  # the book analysed against
    discussion: str  # the pasted text (after cleaning)
    url: str = ""
    platform: DiscussionPlatform = "forum"
    angle: str = ""
    recommendation: Recommendation
    reason: str  # why the discussion is or is not a good opportunity for this book
    missing_context: str = ""  # for "more_context": what the author should add (e.g. the question the replies answer)
    suggested_reply: str = ""  # the agent's draft with [n] citation markers; "" unless the recommendation is contribute
    reply: str = ""  # the reply as the author edited it (starts as suggested_reply)
    edited: bool = False  # True once the author changed the reply
    book_mention: BookMention | None = None  # set when a reply was drafted
    citations: list[Citation] = []  # the passages the reason and the reply draw on, numbered like the markers
    search_queries: list[str] = []  # what the agent searched in the book, in order
    tool_calls: list[ToolCallRecord] = []  # the agent's tool calls, for the trace in the GUI
    platform_issues: list[str] = []  # problems of the draft for the platform (length, AI clichés left after the rewrite)
    # Prompt-injection scan of the discussion (guard.scan_third_party): flagged, not blocked; "rule: excerpt" lines.
    injection_risk: InjectionRisk = "none"
    injection_findings: list[str] = []
    # Output guard of the drafted reply (guard.check_output): an injection that got through, foreign links.
    output_issues: list[str] = []
    humanize: int = 70  # the "how human" setting the reply was written with (analyses before it was a setting: 70)
    tone: Tone = "neutral"  # the tone the reply was written in
    facebook_comment_id: str = ""  # the comment on the author's Facebook Page it answers ("own Page" mode); "" = none
    replied_id: str = ""  # the reply posted as the Page under that comment; "" = not posted from the app
    replied_url: str = ""
    replied_at: datetime | None = None
    model: str | None = None  # chat model that ran the agent
    prompt_version: str | None = None  # e.g. "discussion@3f9a1c2e" (core/prompts.py)
    tokens: int = 0  # LLM tokens used by the whole run
    created_at: datetime
    updated_at: datetime


class DiscussionUpdate(BaseModel):
    """Request body for PATCH /discussions/{id}: the author's edited reply."""

    reply: str = Field(min_length=1, max_length=12000)


# ---------- Reddit scan (Market Intelligence: find discussions for the agent) ----------
ScanTime = Literal["day", "week", "month", "year"]  # how far back the search looks
Fit = Literal["high", "medium", "low"]  # how well the book fits a thread found by the scan
_SUBREDDIT = re.compile(r"^[A-Za-z0-9_]{2,21}$")  # Reddit's rule for subreddit names


class ScanRequest(BaseModel):
    """Request body for POST /projects/{id}/discussions/scan: search Reddit for threads on a topic, for one book."""

    source_id: str = Field(min_length=1)  # the book the threads are ranked for
    topic: str = Field(min_length=1, max_length=300)  # what to search, e.g. "AI future, AI societies, civilizations"
    subreddits: list[str] = Field(default=[], max_length=5)  # e.g. ["Futurology", "r/singularity"]; [] = all of Reddit
    time_range: ScanTime = "month"
    max_results: int = Field(default=10, ge=5, le=20)  # threads per search (Tavily returns at most 20)

    @model_validator(mode="after")
    def _check_subreddits(self) -> "ScanRequest":
        """Accept "Futurology", "r/Futurology" or "/r/Futurology/"; keep each name once; reject anything else."""
        names: list[str] = []
        for raw in self.subreddits:
            name = raw.strip().strip("/").removeprefix("r/").removeprefix("R/").strip()
            if not name:
                continue
            if not _SUBREDDIT.match(name):
                raise ValueError(f"'{raw}' is not a subreddit name (2-21 letters, digits or _).")
            if name.lower() not in (n.lower() for n in names):
                names.append(name)
        self.subreddits = names
        return self


class ScannedThread(BaseModel):
    """A Reddit thread found by the scan, with how well the book fits it."""

    url: str
    subreddit: str  # without "r/"
    title: str
    snippet: str = ""  # the search engine's short excerpt
    full_text: str = ""  # the post and top comments from the page, when the search had them; "" = open the thread
    score: float = 0.0  # the search engine's relevance to the topic (0-1)
    fit: Fit
    why: str  # one sentence: how the book connects, or why it does not
    injection_risk: InjectionRisk = "none"  # prompt-injection scan of title and text (guard.scan_third_party)
    injection_findings: list[str] = []


class ScanResult(BaseModel):
    """The result of a Reddit scan (not saved): the threads, best fit first."""

    source_id: str
    topic: str
    subreddits: list[str] = []
    time_range: ScanTime = "month"
    threads: list[ScannedThread] = []
    found: int = 0  # threads found before ranking (at most MAX_TRIAGE of them are ranked)
    tokens: int = 0
    model: str | None = None
    prompt_version: str | None = None


# ---------- Facebook Page (social/facebook.py) ----------
class FacebookPage(BaseModel):
    """The author's own Facebook Page."""

    id: str
    name: str
    followers: int | None = None
    link: str | None = None


class FacebookPost(BaseModel):
    """A post on the author's Page (by the Page or a visitor), newest first in lists."""

    id: str  # "<page id>_<post id>"
    message: str = ""  # "" for a photo or video without text
    created_time: datetime
    permalink_url: str | None = None
    picture: str | None = None  # the post's image, if any
    comment_count: int = 0


class FacebookComment(BaseModel):
    """A comment on a Page post, or a reply to one (parent_id set). Someone else's text: untrusted."""

    id: str
    post_id: str
    message: str = ""
    created_time: datetime
    author: str | None = None  # the commenter's name; None when Facebook does not return it
    from_page: bool = False  # written by the Page itself (the author's own replies)
    parent_id: str | None = None  # the comment this one replies to
    reply_count: int = 0
    permalink_url: str | None = None
    answered: bool = False  # the Page has replied to it (set by recent_threads)
    injection_risk: InjectionRisk = "none"  # prompt-injection scan of the message (set by GET /facebook/comments)
    injection_findings: list[str] = []


class FacebookPosts(BaseModel):
    """One page of a Page's posts; `after` fetches the next page (None = no more)."""

    items: list[FacebookPost] = []
    after: str | None = None


class FacebookComments(BaseModel):
    """One page of a post's comments; `after` fetches the next page (None = no more)."""

    items: list[FacebookComment] = []
    after: str | None = None


class FacebookThread(BaseModel):
    """A post on the author's Page with its comments (GET /facebook/comments)."""

    post: FacebookPost
    comments: list[FacebookComment] = []  # newest first, the Page's own replies included (from_page)


class FacebookStatus(BaseModel):
    """Response of GET /facebook/status: whether the author's Page is connected (FACEBOOK_PAGE_* in server/.env)."""

    connected: bool
    page: FacebookPage | None = None
    error: str = ""  # why the configured Page could not be reached (e.g. token expired)


class FacebookPublished(BaseModel):
    """What publish_post / reply_to_comment created."""

    id: str
    url: str


# ---------- MCP console (Market Intelligence) ----------
class McpTool(BaseModel):
    """One tool of an MCP server, as listed by tools/list."""

    name: str
    title: str | None = None
    description: str  # what the tool does; the text MCP clients and models read
    input_schema: dict[str, Any]  # JSON Schema of the arguments; the GUI builds its form from it
    read_only: bool | None = None  # the server's read-only hint, if it gives one


class McpServerStatus(BaseModel):
    """An MCP server the app knows, with its live status and tools (GET /mcp-servers)."""

    name: str  # e.g. "mcp-guardrails"
    title: str | None = None
    description: str | None = None
    url: str  # Streamable HTTP endpoint
    audience: Literal["external", "internal"]  # external: for outside clients only; internal: the app uses it too
    status: Literal["active", "offline"]
    error: str | None = None  # why it is offline
    latency_ms: int | None = None  # time to connect and list the tools
    instructions: str | None = None  # the server's usage instructions for clients
    tools: list[McpTool] = []


class McpCallRequest(BaseModel):
    """Request body for POST /mcp-servers/{name}/call: which tool to run with which arguments."""

    tool: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any] = {}


class McpCallResult(BaseModel):
    """One tool call made from the console, with its result; also an entry of the call log."""

    id: str  # e.g. "call_1a2b3c4d"
    server: str
    tool: str
    arguments: dict[str, Any]
    ok: bool  # False if the call failed or the tool reported an error
    structured: Any = None  # the tool's structured result (JSON), if it returned one
    text: str = ""  # the text content of the result, or the error message
    duration_ms: int
    called_at: datetime


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
    request_id: str | None = None  # the HTTP request that caused the call (logs.py); None for older records
    user_id: str | None = None  # the signed-in user who caused it; None for older records and outside sign-in (MCP)


class UsageTotals(BaseModel):
    """Sums over a set of model calls."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    input_cost: float = 0.0  # USD
    output_cost: float = 0.0  # USD
    cost: float = 0.0  # USD, all costs


class UsageBudget(BaseModel):
    """The signed-in user's cost budget (limits.toml) and how much of it is used, in USD (UTC day and month)."""

    spent_today: float
    limit_today: float
    spent_month: float
    limit_month: float


class UsageReport(BaseModel):
    """Response of GET /usage: totals so far, totals per operation, the latest calls and the user's budget."""

    totals: UsageTotals
    by_operation: dict[str, UsageTotals]  # sorted by cost, highest first
    recent: list[UsageRecord]  # newest first
    budget: UsageBudget | None = None  # set by GET /usage


# ---------- Book summaries ----------
class ChapterSummary(BaseModel):
    """Short summary of one chapter (or section) of a book."""

    chapter: str | None  # chapter title from the table of contents; None for text before the first chapter
    first_page: int | None  # page where the chapter starts
    last_page: int | None  # page where the chapter ends
    summary: str  # 2-4 sentences


class BookSummary(BaseModel):
    """Summary of a whole book, made by map-reduce over its chapters (see summary.py).

    Saved in the database (table summaries) and loaded on startup, so it is created only once; kept
    when the book is re-indexed (same content), removed when the book is deleted.
    """

    source_id: str  # the book (source) it summarizes
    summary: str  # what the book is about, in about two paragraphs
    themes: list[str]  # 4-6 key themes as short phrases
    chapters: list[ChapterSummary]  # content chapters in reading order (front/back matter skipped)
    model: str  # chat model that wrote it
    prompt_version: str | None = None  # prompts that wrote it, e.g. "summary@3f9a1c2e"; None = made before versioning
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
