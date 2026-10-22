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
API key) raise ToolError, whose message reaches the client; anything else shows only a generic error. Tools work on the books of the default project.

Local use only: there is no authentication, and the SDK's DNS-rebinding protection accepts only
localhost hosts and origins. Model calls are logged in the usage panel like all others.
"""

from pydantic import BaseModel, Field

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from app.core import state as db
from app.core.llm import GenerationError
from app.core.schemas import Source
from app.rag import qa, vectorstore
from app.rag.library import BookInfo, book_info, book_title, known_books, ready_books
from app.rag.retrieval import retrieve_chunks, source_name

PROJECT_ID = db.DEFAULT_PROJECT_ID  # the project whose books the tools serve

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
def list_books() -> list[BookInfo]:
    """List the author's processed books (ready to search): id, title, author, number of passages,
    whether a summary exists and its key themes. Call this first to get the book_id for the other tools."""
    return [book_info(s) for s in ready_books(PROJECT_ID)]


@book_server.tool(annotations=READ_ONLY)
def search_book(query: str, book_id: str | None = None, k: int = 5) -> list[Passage]:
    """Semantic search in the books: the k passages most similar to the query, best first, each with
    book, chapter, page and similarity score. Use it to find what a book says about a topic, quotes,
    or evidence for a claim. Searches all books unless book_id is given.

    Args:
        query: What to look for, in natural language, e.g. "why towns should own their land".
        book_id: Optional: only search this book (from list_books).
        k: Number of passages to return, 1-20 (default 5).
    """
    if not query.strip():
        raise ToolError("The query is empty.")
    source_ids = [_book(book_id).id] if book_id else None
    try:
        hits = retrieve_chunks(PROJECT_ID, query, max(1, min(k, 20)), source_ids, operation="mcp_search_book")
    except vectorstore.VectorStoreError as e:
        raise ToolError(str(e)) from e
    return [
        Passage(book_id=c.source_id, book=source_name(c.source_id) or c.source_id, chapter=c.location.chapter,
                page=c.location.page, score=score, chunk_id=c.id, text=c.text)
        for c, score in hits
    ]


@book_server.tool(annotations=READ_ONLY)
def get_book_summary(book_id: str) -> BookSummaryResult:
    """The summary of a whole book: what it is about (two paragraphs), its key themes and a short summary
    of every chapter with page ranges. Use it to understand a book before searching it or writing about it.
    Fails if the book has no summary yet (list_books shows has_summary).

    Args:
        book_id: The book (from list_books).
    """
    source = _book(book_id)
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
def ask_book(question: str, book_id: str | None = None) -> Answer:
    """Answer a question from the books, with citations: retrieves the most relevant passages and writes
    an answer using only them, marking sources as [n]. Says so when the books do not answer it. Uses a
    language model call (costs tokens); prefer search_book when you only need passages.

    Args:
        question: The question, e.g. "What does Howard propose against overcrowded cities?".
        book_id: Optional: only use this book (from list_books).
    """
    if not question.strip():
        raise ToolError("The question is empty.")
    source_ids = [_book(book_id).id] if book_id else None
    try:
        result = qa.answer_question(PROJECT_ID, question, 6, source_ids, operation="mcp_ask_book")
    except GenerationError as e:
        raise ToolError(str(e)) from e
    return Answer(answer=result.answer, citations=[
        Citation(number=n, book=source_name(c.source_id) or c.source_id, chapter=c.location.chapter,
                 page=c.location.page, quote=c.quote)
        for n, c in enumerate(result.citations, start=1)
    ])


# ---------- Helpers ----------
def _book(book_id: str) -> Source:
    """A processed book by id; ToolError (its message reaches the client) with the valid ids if unknown."""
    for source in ready_books(PROJECT_ID):
        if source.id == book_id:
            return source
    raise ToolError(f"Unknown book_id '{book_id}'. Known books: {known_books(PROJECT_ID)}.")


def _title(source: Source) -> str:
    """Title part of the readable name, e.g. "Garden Cities of To Morrow"."""
    return book_title(source)
