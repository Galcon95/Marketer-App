"""The client's library of processed books: listing them and finding one by id or title.

Shared by the mcp-book-knowledge MCP server (market/book_server.py) and the chat tools (rag/chat_tools.py),
so both describe the books the same way.
"""

import re

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
    """A processed book by its id, by (part of) its title, or by its author (full name or last name),
    case-insensitive; None if nothing or several match. Lets people and models name a book naturally
    ("political economy", "Mill") instead of using its id."""
    ref = ref.strip().lower()
    if not ref:
        return None
    books = ready_books(project_id)
    for source in books:
        if source.id.lower() == ref:
            return source
    squashed = _squash(ref)
    matches = []
    for source in books:
        title, author = _squash(book_title(source)), _author(source).lower()
        # Titles are compared without spaces and punctuation, so "political economy" finds "ThePrinciplesOfPoliticalEconomy".
        if (squashed and (squashed in title or title in squashed)) or (author and (ref in author or ref.split()[-1] in author.split())):
            matches.append(source)
    return matches[0] if len(matches) == 1 else None


def _squash(text: str) -> str:
    """Lowercase letters and digits only: "The Principles Of …" and "ThePrinciplesOf…" compare equal."""
    return re.sub(r"[^0-9a-z]", "", text.lower())


def _author(source: Source) -> str:
    """Author of a book: from the file name ("Title_Author.pdf"), else from the PDF's metadata; "" if unknown."""
    return (source_name(source.id) or source.filename).partition(" — ")[2] or source.author


def known_books(project_id: str) -> str:
    """The processed books as "id (title)" for error messages, or "none"."""
    return ", ".join(f"{s.id} ({book_title(s)})" for s in ready_books(project_id)) or "none"
