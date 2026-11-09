"""Tools of the Discussion Relevance Agent (discussion.py): what the model may call to research ONE book.

    get_book_profile      the book's title, author, overview, key themes and chapter titles      (no model call)
    search_book_material  passages of the book about a query, above the relevance floor           (vector search)

The book is fixed by the request, so the tools take no book argument: make_tools binds them to a Research object for
one run. Research collects every passage the searches return, numbered 1, 2, ... in the order they were first found;
the numbers stay the same across searches, so the assessment and the reply can cite them as [n] (retrieval.keep_cited
turns them into Citations). A passage found again is returned with its number but without its text.

Saving the result is not a tool: it always happens, in code. Security checks are not tools either: the pasted
discussion is checked before the agent starts, and search queries are checked here (guard.validate_input).

The docstrings are what the model reads to choose a tool, so they say when to use it.
"""

from dataclasses import dataclass, field

from langchain_core.tools import BaseTool, ToolException, tool

from app.core import state as db
from app.core.config import MIN_RELEVANCE
from app.core.guard import validate_input
from app.core.schemas import Chunk
from app.rag.library import book_info, ready_books
from app.rag.retrieval import retrieve_chunks

SEARCH_K = 4  # passages per search
MAX_PASSAGES = 12  # passages per run; further searches return only passages already found


class BookNotReady(LookupError):
    """The book is not a processed book of the project (unknown, another client's, deleted or still processing)."""


@dataclass
class Research:
    """What the agent found out about one book during one run."""

    project_id: str
    source_id: str
    passages: list[tuple[Chunk, float]] = field(default_factory=list)  # numbered from 1, in order found
    queries: list[str] = field(default_factory=list)  # every search, in order
    profile_read: bool = False

    def number(self, chunk: Chunk, score: float) -> tuple[int, bool]:
        """The passage's number, adding it if it is new and there is room. Returns (number, is_new); number 0 means
        it was not added because MAX_PASSAGES is reached."""
        for n, (known, _) in enumerate(self.passages, start=1):
            if known.id == chunk.id:
                return n, False
        if len(self.passages) >= MAX_PASSAGES:
            return 0, False
        self.passages.append((chunk, score))
        return len(self.passages), True


def start_research(project_id: str, source_id: str) -> Research:
    """A new Research for a processed book of the project.

    Raises:
        BookNotReady: If source_id is not a ready book of this project.
    """
    if not any(s.id == source_id for s in ready_books(project_id)):
        raise BookNotReady(f"Book {source_id} is not a processed book of this client.")
    return Research(project_id=project_id, source_id=source_id)


def book_profile(research: Research) -> dict:
    """The book's profile as a dict (the result of get_book_profile)."""
    info = book_info(db.sources[research.source_id])
    summary = db.summaries.get(research.source_id)
    research.profile_read = True
    profile = {"title": info.title, "author": info.author, "passages": info.chunks}
    if summary is None:
        return profile | {"overview": "", "themes": [], "chapters": [],
                          "note": "No summary of this book exists yet; search the book directly."}
    return profile | {"overview": summary.summary, "themes": summary.themes,
                      "chapters": [c.chapter for c in summary.chapters if c.chapter]}


def search_material(research: Research, query: str) -> dict:
    """Search the book (the result of search_book_material).

    Raises:
        ToolException: If the query is empty or too long (the model gets the message and can try again).
    """
    checked = validate_input(query, "search_query")
    if not checked.ok:
        raise ToolException("; ".join(p.message for p in checked.problems if p.severity == "error"))
    query = checked.cleaned
    research.queries.append(query)
    hits = retrieve_chunks(research.project_id, query, SEARCH_K, [research.source_id], operation="discussion")
    relevant = [(chunk, score) for chunk, score in hits if score >= MIN_RELEVANCE]
    passages, full = [], False
    for chunk, score in relevant:
        n, new = research.number(chunk, score)
        if n == 0:
            full = True
            continue
        passage = {"n": n, "chapter": chunk.location.chapter, "page": chunk.location.page, "similarity": score}
        passages.append(passage | ({"text": chunk.text} if new else {"already_found": True}))
    result: dict = {"query": query, "passages": passages}
    if not relevant:
        best = max((score for _, score in hits), default=0.0)
        result["note"] = (f"No passage of the book is relevant enough to this query (best similarity {best:.2f}, "
                          f"minimum {MIN_RELEVANCE:.2f}). Try other words, or conclude the book does not cover it.")
    elif full:
        result["note"] = f"The limit of {MAX_PASSAGES} passages per discussion is reached; work with those found."
    return result


def make_tools(research: Research) -> list[BaseTool]:
    """The agent's tools for one run, bound to its Research, in the order the model sees them."""

    @tool(parse_docstring=True)
    def get_book_profile() -> dict:
        """Read the profile of the author's book: title, author, an overview of what it is about, its key themes and
        its chapter titles. Use it first, to see which parts of the book could relate to the discussion and what to
        search for.
        """
        return book_profile(research)

    @tool(parse_docstring=True)
    def search_book_material(query: str) -> dict:
        """Search the author's book for passages about one topic. Returns numbered passages (cite passage n as [n])
        with chapter, page and similarity; passages found by an earlier search keep their number and come without
        text. Search once per distinct point of the discussion, in the words the book would use, not the discussion's
        exact wording. If nothing is relevant, the result says so.

        Args:
            query: One topic to look for, in a few words or one sentence, e.g. "how a city could use AI to plan housing".
        """
        return search_material(research, query)

    return [get_book_profile, search_book_material]
