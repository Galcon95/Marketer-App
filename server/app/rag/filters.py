"""Structured retrieval ("self-querying"): metadata filters taken from the question itself.

    question ──(mentions a book, chapter or page?)──► extract_filters ──► resolve_filters ──► metadata filter
                 might_filter (code, no model call)      model, structured     code: references →     for Chroma
                                                         output (QueryFilters)  real metadata values  (vectorstore)

"What does chapter 17 of Butler say about short selling?" → book "Butler", chapter "17" → source src_908396aa,
chapter "CHAPTER XVII. SHORT SELLING". The model only extracts what the question says; resolve_filters matches it
against the books and chapters that exist, so a filter can never contain an invented value. A reference that matches
nothing is dropped (and reported), never turned into an empty search. Used by the Q&A graph (qa.py, "filter" node).
"""

import re

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.core import state as db
from app.core.llm import chat_model, tokens_used
from app.rag.library import book_title, find_book, ready_books
from app.rag.retrieval import source_name

# Words that suggest the question is about a part of a book; without them (and without a book or author named),
# no filter is extracted and no model call is made.
_HINTS = re.compile(r"\b(chapters?|chap\.|ch\.|pages?|pp?\.|parts?|sections?|books?|preface|introduction|appendix|"
                    r"postscript|foreword)\b", re.IGNORECASE)
_ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}

FILTER_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Read the user's question about a library of books and extract the metadata filters it states explicitly, "
     "for a search in the books. Only extract what the question says; leave a field empty when it is not "
     "mentioned. Never guess a book or chapter from the topic alone.\n\nBooks in the library:\n{books}"),
    ("human", "{question}"),
])


class QueryFilters(BaseModel):
    """What the question restricts the search to (structured output of the extraction step)."""

    book: str | None = Field(None, description="The book the question names, by title, part of the title or author, "
                                               "as written in the question; empty if none is named.")
    chapter: str | None = Field(None, description="The chapter, part, book or section the question names, e.g. '17', "
                                                  "'IV', 'Short Selling', 'preface'; empty if none.")
    page_from: int | None = Field(None, description="First page if the question names a page or page range.")
    page_to: int | None = Field(None, description="Last page if the question names a page range; same as page_from "
                                                  "for a single page.")


class ResolvedFilters(BaseModel):
    """The filters that apply, as real metadata values, plus a readable description for the GUI."""

    source_ids: list[str] | None = None  # books to search; None = all (or the user's "Working on" choice)
    chapters: list[str] | None = None  # exact chapter metadata values
    page_from: int | None = None
    page_to: int | None = None
    description: str = ""  # e.g. "Successful Stock Speculation · CHAPTER XVII. SHORT SELLING"
    notes: list[str] = []  # references that matched nothing, e.g. "no chapter 40 in the book"

    def where(self) -> dict | None:
        """The extra Chroma metadata conditions (chapter, pages); the book goes through source_ids."""
        conditions = []
        if self.chapters:
            conditions.append({"chapter": {"$in": self.chapters}})
        if self.page_from is not None:
            conditions.append({"page": {"$gte": self.page_from}})
        if self.page_to is not None:
            conditions.append({"page": {"$lte": self.page_to}})
        return None if not conditions else conditions[0] if len(conditions) == 1 else {"$and": conditions}


# ---------- Public API ----------
def might_filter(project_id: str, question: str) -> bool:
    """True if the question may restrict the search: it mentions a chapter, page, part, ... or names a library book
    (two title words in a row) or an author (last name). Decides whether the extraction model call is made."""
    if _HINTS.search(question):
        return True
    text = question.lower()
    for source in ready_books(project_id):
        name = source_name(source.id) or source.filename
        title, _, author = name.partition(" — ")
        # Significant title words (4+ letters; "ThePrinciplesOf..." split at capitals); two in a row name the book,
        # compared by their first 3 letters so word endings may differ ("Garden City" for "Garden Cities").
        words = [w for w in re.findall(r"[a-z]+", re.sub(r"(?<=[a-z])(?=[A-Z])", " ", title).lower()) if len(w) >= 4]
        if any(re.search(rf"\b{a[:3]}\w*\s+{b[:3]}\w*", text) for a, b in zip(words, words[1:])):
            return True
        surname = (author or source.author).split()[-1:]
        if surname and len(surname[0]) > 2 and re.search(rf"\b{re.escape(surname[0].lower())}\b", text):
            return True
    return False


def extract_filters(project_id: str, question: str) -> tuple[QueryFilters, int]:
    """The filters the question states (model call with structured output, temperature 0) and the tokens used."""
    books = "\n".join(f"- {source_name(s.id) or s.filename}" for s in ready_books(project_id)) or "(none)"
    model = chat_model(0.0).with_structured_output(QueryFilters, include_raw=True)
    result = (FILTER_PROMPT | model).invoke({"books": books, "question": question})
    return result.get("parsed") or QueryFilters(), tokens_used(result["raw"])


def resolve_filters(project_id: str, filters: QueryFilters, source_ids: list[str] | None) -> ResolvedFilters:
    """Turn extracted references into real metadata values.

    Args:
        project_id: The project (client).
        filters: What the question names.
        source_ids: The books the user chose ("Working on"), or None for all. A book named in the question replaces
            this choice, because the question is more specific.
    """
    resolved = ResolvedFilters(source_ids=source_ids)
    parts, notes = [], []
    if filters.book:
        book = find_book(project_id, filters.book)
        if book:
            resolved.source_ids = [book.id]
            parts.append(book_title(book))
        else:
            notes.append(f"no single book matches '{filters.book}'")
    if filters.chapter:
        chapters = _matching_chapters(project_id, filters.chapter, resolved.source_ids)
        if chapters:
            resolved.chapters = chapters
            parts.append(chapters[0] if len(chapters) == 1 else f"{len(chapters)} chapters named '{filters.chapter}'")
        else:
            notes.append(f"no chapter '{filters.chapter}' found")
    if filters.page_from is not None or filters.page_to is not None:
        first = filters.page_from if filters.page_from is not None else filters.page_to
        last = filters.page_to if filters.page_to is not None else filters.page_from
        resolved.page_from, resolved.page_to = min(first, last), max(first, last)
        parts.append(f"p. {first}" if first == last else f"pp. {resolved.page_from}-{resolved.page_to}")
    resolved.description = " · ".join(parts)
    resolved.notes = notes
    return resolved


# ---------- Helpers ----------
def _matching_chapters(project_id: str, ref: str, source_ids: list[str] | None) -> list[str]:
    """The chapter metadata values (of the given books, or all) that the reference names, in reading order.

    A number matches the chapter's number written in Arabic or Roman numerals ("17", "XVII" → "CHAPTER XVII. ...");
    words match the chapter title ("short selling" → "CHAPTER XVII. SHORT SELLING"); "preface" matches "Preface.".
    """
    ref = ref.strip().lower()
    ref = re.sub(r"^(chapter|chap\.|ch\.|part|book|section)\s+", "", ref)  # "chapter 17" → "17"
    number = int(ref) if ref.isdigit() else _roman_to_int(ref)
    chapters = []
    for chunk in db.chunks.values():
        chapter = chunk.location.chapter
        if not chapter or chapter in chapters or (source_ids and chunk.source_id not in source_ids):
            continue
        if number is not None:
            if _chapter_number(chapter) == number:
                chapters.append(chapter)
        elif len(ref) >= 3 and ref in chapter.lower():
            chapters.append(chapter)
    return chapters


def _chapter_number(chapter: str) -> int | None:
    """The number of a chapter heading: "CHAPTER XVII. SHORT SELLING" → 17, "Book IV. Influence ..." → 4."""
    match = re.match(r"\s*(?:chapter|part|book|section)\s+([ivxlcdm]+|\d+)\b", chapter, re.IGNORECASE)
    if not match:
        return None
    token = match.group(1).lower()
    return int(token) if token.isdigit() else _roman_to_int(token)


def _roman_to_int(text: str) -> int | None:
    """A Roman numeral as int ("xvii" → 17), None if the text is not one."""
    if not text or any(c not in _ROMAN for c in text):
        return None
    total = 0
    for i, c in enumerate(text):
        value = _ROMAN[c]
        total += -value if i + 1 < len(text) and _ROMAN[text[i + 1]] > value else value
    return total
