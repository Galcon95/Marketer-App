"""Book summaries with LangGraph map-reduce: summarize every chapter, then the whole book.

    START ─► Send × chapters ─► summarize_chapter (parallel, map) ─► combine (reduce) ─► END

    map      each chapter's text (its chunks joined in order) → 2-4 sentence ChapterSummary;
             front/back matter (contents, index, license, footnotes, ...) is answered with SKIP and dropped
    reduce   all chapter summaries in reading order → book summary + key themes (structured output)

Unlike retrieval (top-k chunks), this reads the whole book, so it can say what the book is about
overall. The result is saved next to the book (.summary.json) and used as background in grounded
generation (generation.py). Runs are traced in LangSmith as "summarize_book" when tracing is on.
"""

import logging
import operator
from datetime import datetime, timezone
from functools import cache
from typing import Annotated, TypedDict

from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field

from app.core import state as db
from app.core import storage
from app.core.config import LLM_MODEL
from app.core.llm import GenerationError, chat_model, is_configured, tokens_used
from app.core.schemas import BookSummary, ChapterSummary, Chunk, Source
from app.rag.retrieval import source_name

logger = logging.getLogger(__name__)

MAX_SECTION_CHARS = 120_000  # about 30k tokens; longer chapters are cut to keep each map call affordable
MAX_PARALLEL_CALLS = 8  # chapter summaries requested at the same time

CHAPTER_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You summarize one section of a book for a book marketer. Write 2-4 sentences: what this section "
     "argues or tells, with its key ideas, names and memorable points. Use only the given text.\n"
     "If the section is not part of the book's actual content (table of contents, list of illustrations, "
     "index, footnotes, license, transcriber's note, publisher or e-book information), reply with exactly: SKIP"),
    ("human", "Book: {book}\nSection: {chapter} ({pages})\n\n{text}"),
])

BOOK_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You help a book marketer understand a book. From the chapter summaries, write an overview of the "
     "whole book. Use only the chapter summaries; never invent facts, names or numbers."),
    ("human", "Book: {book}\n\nChapter summaries in reading order:\n\n{summaries}"),
])


class BookOverview(BaseModel):
    """Structured output of the reduce step."""

    summary: str = Field(description="What the book is about, in two paragraphs of 150-220 words in total: "
                                     "the problem it addresses, its central idea or argument, and who it is for.")
    themes: list[str] = Field(description="4-6 key themes of the book, each a short phrase.")


class _Section(TypedDict):
    """Input of one map task: a chapter's text and position."""

    index: int  # position in the book, for sorting the results
    book: str
    chapter: str | None
    first_page: int | None
    last_page: int | None
    text: str


class _SummaryState(TypedDict, total=False):
    """State of the map-reduce graph. Lists and token counts from parallel map tasks are added up."""

    book: str
    sections: list[_Section]
    chapter_summaries: Annotated[list[tuple[int, ChapterSummary]], operator.add]
    tokens: Annotated[int, operator.add]
    overview: BookOverview


# ---------- Public API ----------
def summarize_source(source: Source) -> BookSummary:
    """Create (or recreate) the summary of a processed book, save it, and keep it in memory.

    Args:
        source: A source with status "ready" (its chunks are in memory).

    Returns:
        The new summary.

    Raises:
        GenerationError: 503 if no API key is configured, 409 if the book has no chunks,
            502 if a model call fails.
    """
    if not is_configured():
        raise GenerationError(503, "No API key set. Add OPENROUTER_API_KEY (or OPENAI_API_KEY) and restart the server.")
    sections = _sections(source)
    if not sections:
        raise GenerationError(409, f"'{source.filename}' has no chunks to summarize. Process it first.")
    try:
        state = _graph().invoke(
            {"book": source_name(source.id) or source.filename, "sections": sections, "tokens": 0, "chapter_summaries": []},
            config={"run_name": "summarize_book", "tags": ["summary"], "max_concurrency": MAX_PARALLEL_CALLS,
                    "metadata": {"source_id": source.id, "project_id": source.project_id, "llm_model": LLM_MODEL,
                                 "operation": "summarize_book"}},
        )
    except GenerationError:
        raise
    except Exception as e:
        logger.exception("Summary of %s failed", source.id)
        raise GenerationError(502, f"The language model call failed: {e}") from e

    summary = BookSummary(
        source_id=source.id,
        summary=state["overview"].summary,
        themes=state["overview"].themes,
        chapters=[s for _, s in sorted(state["chapter_summaries"], key=lambda item: item[0])],
        model=LLM_MODEL,
        tokens=state["tokens"],
        created_at=datetime.now(timezone.utc),
    )
    storage.write_summary(source, summary)
    db.summaries[source.id] = summary
    logger.info("Summarized %s: %d chapters, %d tokens", source.id, len(summary.chapters), summary.tokens)
    return summary


# ---------- Graph ----------
@cache
def _graph():
    """Build and compile the map-reduce graph: START → summarize_chapter × N (via Send) → combine → END."""
    builder = StateGraph(_SummaryState)
    builder.add_node("summarize_chapter", _summarize_chapter)
    builder.add_node("combine", _combine)
    builder.add_conditional_edges(START, _fan_out, ["summarize_chapter"])
    builder.add_edge("summarize_chapter", "combine")
    builder.add_edge("combine", END)
    return builder.compile()


def _fan_out(state: _SummaryState) -> list[Send]:
    """Map step dispatch: one summarize_chapter task per chapter, run in parallel."""
    return [Send("summarize_chapter", section) for section in state["sections"]]


def _summarize_chapter(section: _Section) -> _SummaryState:
    """Map node: summarize one chapter in 2-4 sentences; front/back matter answered with SKIP is dropped."""
    pages = _pages_label(section["first_page"], section["last_page"])
    reply = (CHAPTER_PROMPT | chat_model()).invoke({
        "book": section["book"], "chapter": section["chapter"] or "Front matter", "pages": pages, "text": section["text"],
    })
    text = str(reply.content).strip()
    if text.upper().startswith("SKIP"):
        return {"chapter_summaries": [], "tokens": tokens_used(reply)}
    summary = ChapterSummary(chapter=section["chapter"], first_page=section["first_page"],
                             last_page=section["last_page"], summary=text)
    return {"chapter_summaries": [(section["index"], summary)], "tokens": tokens_used(reply)}


def _combine(state: _SummaryState) -> _SummaryState:
    """Reduce node: turn the chapter summaries (in reading order) into a book overview with themes."""
    chapters = [s for _, s in sorted(state["chapter_summaries"], key=lambda item: item[0])]
    if not chapters:
        raise GenerationError(502, "The book has no content chapters to summarize.")
    listing = "\n\n".join(f"{c.chapter or 'Front matter'} ({_pages_label(c.first_page, c.last_page)}):\n{c.summary}" for c in chapters)
    result = chat_model().with_structured_output(BookOverview, include_raw=True).invoke(
        BOOK_PROMPT.invoke({"book": state["book"], "summaries": listing}))
    if result.get("parsed") is None:
        raise GenerationError(502, f"The model returned an unreadable overview: {result.get('parsing_error')}")
    return {"overview": result["parsed"], "tokens": tokens_used(result["raw"])}


# ---------- Helpers ----------
def _sections(source: Source) -> list[_Section]:
    """Group a book's chunks into chapters, in reading order, with their joined text and page range.

    Consecutive chunks with the same chapter form one section. Neighbouring chunks overlap by a few
    sentences; that small repetition does not matter for a summary.
    """
    chunks: list[Chunk] = sorted((c for c in db.chunks.values() if c.source_id == source.id), key=lambda c: c.id)
    book = source_name(source.id) or source.filename
    sections: list[_Section] = []
    for chunk in chunks:
        if sections and sections[-1]["chapter"] == chunk.location.chapter:
            current = sections[-1]
            current["text"] = (current["text"] + "\n\n" + chunk.text)[:MAX_SECTION_CHARS]
            current["last_page"] = chunk.location.page or current["last_page"]
        else:
            sections.append(_Section(index=len(sections), book=book, chapter=chunk.location.chapter,
                                     first_page=chunk.location.page, last_page=chunk.location.page, text=chunk.text))
    return sections


def _pages_label(first: int | None, last: int | None) -> str:
    """Page range for prompts and display, e.g. "pp. 13-15", "p. 9" or "pages unknown"."""
    if first is None:
        return "pages unknown"
    return f"p. {first}" if last in (None, first) else f"pp. {first}-{last}"
