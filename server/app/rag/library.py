"""The client's library of processed books: listing them and finding one by id or title.

Shared by the mcp-book-knowledge MCP server (market/book_server.py) and the chat tools (rag/chat_tools.py),
so both describe the books the same way.
"""

from pydantic import BaseModel, Field

from app.core import state as db
from app.core.schemas import Source
from app.rag.retrieval import source_name


class BookInfo(BaseModel):
    """One processed book."""

    book_id: str = Field(description="Id to pass to the other tools, e.g. 'src_81a0e753'.")
    title: str
    author: str = Field(description="Author from the file name or the PDF; empty if unknown.")
    chunks: int = Field(description="Number of searchable passages.")
    has_summary: bool = Field(description="Whether a summary of the book exists.")
    themes: list[str] = Field(description="Key themes from the summary; empty without a summary.")


def ready_books(project_id: str) -> list[Source]:
    """The processed books of a project (status ready), in upload order."""
    return [s for s in db.sources.values() if s.project_id == project_id and s.status == "ready" and s.kind == "document"]


def book_title(source: Source) -> str:
    """Title part of the readable name, e.g. "Garden Cities of To Morrow"."""
    return (source_name(source.id) or source.filename).split(" — ")[0]


def book_info(source: Source) -> BookInfo:
    """BookInfo of a book: id, title, author, size, summary state and themes."""
    name = source_name(source.id) or source.filename
    title, _, author = name.partition(" — ")
    summary = db.summaries.get(source.id)
    return BookInfo(book_id=source.id, title=title, author=author, chunks=source.chunk_count,
                    has_summary=summary is not None, themes=summary.themes if summary else [])


def find_book(project_id: str, ref: str) -> Source | None:
    """A processed book by its id, or by (part of) its title, case-insensitive; None if nothing or several match."""
    ref = ref.strip().lower()
    books = ready_books(project_id)
    for source in books:
        if source.id.lower() == ref:
            return source
    matches = [s for s in books if ref and ref in book_title(s).lower()]
    return matches[0] if len(matches) == 1 else None


def known_books(project_id: str) -> str:
    """The processed books as "id (title)" for error messages, or "none"."""
    return ", ".join(f"{s.id} ({book_title(s)})" for s in ready_books(project_id)) or "none"
