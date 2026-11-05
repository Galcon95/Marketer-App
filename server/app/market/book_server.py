"""mcp-book-knowledge: the Knowledge Hub's books as an MCP server (Model Context Protocol).

    MCP client (LangGraph agent, MCP Inspector, Claude Code, ...)
        │  Streamable HTTP, POST http://127.0.0.1:8000/mcp
        ▼
    book_server (MCPServer, mounted in the FastAPI app by server.py)
        list_books        the processed books with title, author, themes        (no model call)
        search_book       best-matching passages with chapter, page, score       (one embedding call)
        get_book_summary  overview, themes and chapter summaries                 (no model call)
        ask_book          a cited answer, like "Ask your book" in the GUI        (embedding + one LLM call)

It runs inside the API process, so it serves the same in-memory books, chunks and summaries as the
GUI, and newly processed books are available at once. The tools are thin wrappers around app/rag;
their docstrings are the descriptions MCP clients (and the agents reading them) see, so they say
exactly what each tool returns and when to use it. Expected failures (unknown book, no summary, no
API key) raise ToolError, whose message reaches the client; anything else shows only a generic error.

Every request needs a personal API key or a sign-in token (core/mcp_auth.py checks it before the server sees the
request). The tools work on the caller's own library (accounts.client_of), never another user's. The tools that
call a model (search_book, ask_book) have the same limits as the app (deps.llm_limits: budgets, requests per
minute), and their costs are logged for the caller. The SDK's DNS-rebinding protection accepts only localhost
hosts and origins.
"""

from pydantic import BaseModel, Field

from fastapi import HTTPException
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from app.api.deps import llm_limits
from app.core import accounts, guard, mcp_auth
from app.core import state as db
from app.core.auth import User
from app.core.llm import GenerationError
from app.core.schemas import Source
from app.rag import qa, vectorstore
from app.rag.library import BookInfo, book_info, book_title, find_book, known_books, ready_books
from app.rag.retrieval import retrieve_chunks, source_name

book_server = MCPServer(
    name="mcp-book-knowledge",
    title="Book knowledge",
    description="Search, summaries and cited answers from the author's books (the marketer app's Knowledge Hub).",
    instructions=(
        "Use list_books first to get the book ids. Use search_book to find passages (with page numbers) "
        "about a topic, get_book_summary to understand a whole book, and ask_book for a written answer "
        "with citations. Quote and cite only what these tools return."
    ),
)

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


# ---------- Results (BookInfo comes from rag/library.py) ----------
class Passage(BaseModel):
    """One passage found by search_book."""

    book_id: str
    book: str = Field(description="Book title (and author).")
    chapter: str | None
    page: int | None = Field(description="Page in the PDF, for citing.")
    score: float = Field(description="Similarity to the query, about 0-1; above 0.45 is usually relevant.")
    chunk_id: str
    text: str


class Chapter(BaseModel):
    """Summary of one chapter."""

    chapter: str | None
    pages: str = Field(description="Page range, e.g. '13-27'; empty if unknown.")
    summary: str


class BookSummaryResult(BaseModel):
    """Summary of a whole book."""

    book_id: str
    title: str
    summary: str
    themes: list[str]
    chapters: list[Chapter]


class Citation(BaseModel):
    """A passage cited in an answer as [n]."""

    number: int = Field(description="The n of the [n] marker in the answer.")
    book: str
    chapter: str | None
    page: int | None
    quote: str


class Answer(BaseModel):
    """A cited answer from ask_book."""

    answer: str = Field(description="Answer with [n] markers that refer to the citations.")
    citations: list[Citation]


# ---------- Tools ----------
@book_server.tool(annotations=READ_ONLY)
def list_books(ctx: Context) -> list[BookInfo]:
    """List the author's processed books (ready to search): id, title, author, number of passages,
    whether a summary exists and its key themes. Call this first to get the book_id for the other tools."""
    _, project_id = _caller(ctx)
    return [book_info(s) for s in ready_books(project_id)]


@book_server.tool(annotations=READ_ONLY)
def search_book(ctx: Context, query: str, book_id: str | None = None, k: int = 5) -> list[Passage]:
    """Semantic search in the books: the k passages most similar to the query, best first, each with
    book, chapter, page and similarity score. Use it to find what a book says about a topic, quotes,
    or evidence for a claim. Searches all books unless book_id is given.

    Args:
        query: What to look for, in natural language, e.g. "why towns should own their land".
        book_id: Optional: only search this book, by its id from list_books, its title (or part of it) or its author.
        k: Number of passages to return, 1-20 (default 5).
    """
    user, project_id = _caller(ctx)
    query = _checked(query, "search_query", check_injection=False)  # only embedded, never a prompt
    source_ids = [_book(project_id, book_id).id] if book_id else None
    _within_limits(user)
    try:
        hits = retrieve_chunks(project_id, query, max(1, min(k, 20)), source_ids, operation="mcp_search_book")
    except vectorstore.VectorStoreError as e:
        raise ToolError(str(e)) from e
    return [
        Passage(book_id=c.source_id, book=source_name(c.source_id) or c.source_id, chapter=c.location.chapter,
                page=c.location.page, score=score, chunk_id=c.id, text=c.text)
        for c, score in hits
    ]


@book_server.tool(annotations=READ_ONLY)
def get_book_summary(ctx: Context, book_id: str) -> BookSummaryResult:
    """The summary of a whole book: what it is about (two paragraphs), its key themes and a short summary
    of every chapter with page ranges. Use it to understand a book before searching it or writing about it.
    Fails if the book has no summary yet (list_books shows has_summary).

    Args:
        book_id: The book, by its id from list_books, its title (or part of it) or its author.
    """
    _, project_id = _caller(ctx)
    source = _book(project_id, book_id)
    summary = db.summaries.get(source.id)
    if summary is None:
        raise ToolError(f"'{_title(source)}' has no summary yet. Create one in the Knowledge Hub of the marketer app.")
    return BookSummaryResult(
        book_id=source.id, title=_title(source), summary=summary.summary, themes=summary.themes,
        chapters=[Chapter(chapter=c.chapter, summary=c.summary,
                          pages="-".join(str(p) for p in dict.fromkeys((c.first_page, c.last_page)) if p is not None))
                  for c in summary.chapters],
    )


@book_server.tool(annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=False,
                                              open_world_hint=False))
def ask_book(ctx: Context, question: str, book_id: str | None = None) -> Answer:
    """Answer a question from the books, with citations: retrieves the most relevant passages and writes
    an answer using only them, marking sources as [n]. Says so when the books do not answer it. Uses a
    language model call (costs tokens); prefer search_book when you only need passages.

    Args:
        question: The question, e.g. "What does Howard propose against overcrowded cities?".
        book_id: Optional: only use this book, by its id from list_books, its title (or part of it) or its author.
    """
    user, project_id = _caller(ctx)
    question = _checked(question, "question", check_injection=True)
    source_ids = [_book(project_id, book_id).id] if book_id else None
    _within_limits(user)
    try:
        result = qa.answer_question(project_id, question, 6, source_ids, operation="mcp_ask_book")
    except GenerationError as e:
        raise ToolError(str(e)) from e
    return Answer(answer=result.answer, citations=[
        Citation(number=n, book=source_name(c.source_id) or c.source_id, chapter=c.location.chapter,
                 page=c.location.page, quote=c.quote)
        for n, c in enumerate(result.citations, start=1)
    ])


# ---------- Helpers ----------
def _caller(ctx: Context) -> tuple[User, str]:
    """The user whose key or sign-in token the request carries (mcp_auth.py) and the id of their own project
    (created on first use, like GET /me in the app).

    Raises:
        ToolError: Without a checked user (cannot happen behind RequireMcpAuth), or if the project cannot be saved.
    """
    request = ctx.request_context.request
    user = mcp_auth.user_of(request.scope) if request is not None else None
    if user is None:
        raise ToolError("Not signed in: send a personal API key.")
    try:
        return user, accounts.client_of(user).id
    except OSError as e:
        raise ToolError("Your library could not be opened, please try again.") from e


def _within_limits(user: User) -> None:
    """The app's limits for model calls (limits.toml via deps.llm_limits); ToolError with its message if one is
    reached (daily or monthly budget, the app's budget, requests per minute)."""
    try:
        llm_limits(user)
    except HTTPException as e:
        raise ToolError(str(e.detail)) from e


def _book(project_id: str, book_id: str) -> Source:
    """A processed book of the project by its id, (part of) its title or its author (library.find_book); ToolError
    (its message reaches the client) listing the project's books if nothing or several books match."""
    source = find_book(project_id, book_id)
    if source is None:
        raise ToolError(f"No single book matches '{book_id}'. Known books: {known_books(project_id)}.")
    return source


def _title(source: Source) -> str:
    """Title part of the readable name, e.g. "Garden Cities of To Morrow"."""
    return book_title(source)


def _checked(text: str, kind: guard.InputKind, *, check_injection: bool) -> str:
    """The cleaned text (guard.py), or ToolError if it is empty, too long or (with check_injection) a likely
    prompt injection; the same checks as the app's own endpoints."""
    checked = guard.validate_input(text, kind)
    if not checked.ok:
        raise ToolError(" ".join(p.message for p in checked.problems if p.severity == "error"))
    if check_injection and guard.check_prompt_injection(checked.cleaned).risk == "high":
        raise ToolError("The text looks like an attempt to change the assistant's instructions and was blocked.")
    return checked.cleaned
