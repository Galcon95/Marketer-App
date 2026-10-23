"""Unit tests of structured retrieval (app/rag/filters.py) without a model: the gate that decides whether to
extract filters, and the resolution of book/chapter/page references to real metadata values. A small made-up
library is put into the in-memory state for each test (and removed again)."""

from datetime import datetime, timezone

import pytest

from app.core import state as db
from app.core.schemas import Chunk, ChunkLocation, Source
from app.rag.filters import QueryFilters, _roman_to_int, might_filter, resolve_filters

PROJECT = "test-project"
CHAPTERS = {  # source id → its chapters
    "src_stock": ["CHAPTER XVI. MARGINAL TRADING", "CHAPTER XVII. SHORT SELLING", "CHAPTER XX. PUTS AND CALLS"],
    "src_garden": ["INTRODUCTION.", "CHAPTER IV. THE REVENUE OF GARDEN CITY"],
}


@pytest.fixture(autouse=True)
def library(monkeypatch):
    """Two ready books with a few chapters, replacing the app's sources and chunks during the test."""
    now = datetime.now(timezone.utc)
    sources = {
        "src_stock": Source(id="src_stock", project_id=PROJECT, filename="Successful Stock Speculation.pdf", kind="document",
                            size_bytes=1, status="ready", progress=100, chunk_count=3, created_at=now, author="J. J. Butler"),
        "src_garden": Source(id="src_garden", project_id=PROJECT, filename="Garden-Cities-of-To-Morrow_Ebenezer-Howard.pdf",
                             kind="document", size_bytes=1, status="ready", progress=100, chunk_count=2, created_at=now),
    }
    chunks = {}
    for source_id, chapters in CHAPTERS.items():
        for n, chapter in enumerate(chapters):
            chunk_id = f"chk_{source_id}_{n}"
            chunks[chunk_id] = Chunk(id=chunk_id, source_id=source_id, text="text", token_count=1,
                                     location=ChunkLocation(chapter=chapter, page=10 + n))
    monkeypatch.setattr(db, "sources", sources)
    monkeypatch.setattr(db, "chunks", chunks)


# ---------- might_filter: when the extraction model call is made ----------
@pytest.mark.parametrize("question", [
    "What does chapter 17 say about short selling?",
    "Summarize pages 20-25",
    "What does Butler say about margin?",  # author
    "How is Garden City financed?",  # title words, with a different ending ("Cities")
    "Explain the basics of stock speculation",
])
def test_questions_naming_a_book_chapter_or_page_are_filtered(question):
    assert might_filter(PROJECT, question)


@pytest.mark.parametrize("question", ["What is a bucket shop?", "Is speculation gambling?", "What is intrinsic value?"])
def test_ordinary_questions_skip_the_model_call(question):
    assert not might_filter(PROJECT, question)


# ---------- resolve_filters: references → real metadata values ----------
@pytest.mark.parametrize("chapter", ["17", "XVII", "chapter 17", "short selling", "Short Selling"])
def test_chapter_by_number_numeral_or_title(chapter):
    resolved = resolve_filters(PROJECT, QueryFilters(chapter=chapter), None)
    assert resolved.chapters == ["CHAPTER XVII. SHORT SELLING"]
    assert resolved.where() == {"chapter": {"$in": ["CHAPTER XVII. SHORT SELLING"]}}


def test_book_by_author_or_title_part_replaces_the_working_on_choice():
    for ref in ("Butler", "stock", "Successful Stock Speculation"):
        assert resolve_filters(PROJECT, QueryFilters(book=ref), ["src_garden"]).source_ids == ["src_stock"]
    assert resolve_filters(PROJECT, QueryFilters(book="Howard"), None).source_ids == ["src_garden"]


def test_book_titles_match_without_spaces_and_punctuation():
    for ref in ("Garden Cities of To-Morrow", "gardencities", "src_garden"):
        assert resolve_filters(PROJECT, QueryFilters(book=ref), None).source_ids == ["src_garden"]


def test_chapter_number_is_looked_up_in_the_named_book_only():
    resolved = resolve_filters(PROJECT, QueryFilters(book="Howard", chapter="4"), None)
    assert resolved.chapters == ["CHAPTER IV. THE REVENUE OF GARDEN CITY"]
    assert resolved.description == "Garden Cities of To Morrow · CHAPTER IV. THE REVENUE OF GARDEN CITY"


def test_unknown_references_are_dropped_with_a_note_not_turned_into_an_empty_search():
    resolved = resolve_filters(PROJECT, QueryFilters(book="cooking", chapter="40"), None)
    assert resolved.source_ids is None and resolved.chapters is None and resolved.where() is None
    assert resolved.notes == ["no single book matches 'cooking'", "no chapter '40' found"]


def test_page_range_becomes_two_conditions_in_order():
    resolved = resolve_filters(PROJECT, QueryFilters(page_from=25, page_to=20), None)
    assert (resolved.page_from, resolved.page_to) == (20, 25)
    assert resolved.where() == {"$and": [{"page": {"$gte": 20}}, {"page": {"$lte": 25}}]}
    assert resolve_filters(PROJECT, QueryFilters(page_from=13), None).description == "p. 13"


@pytest.mark.parametrize(("text", "value"), [("iv", 4), ("xvii", 17), ("xx", 20), ("mcmxcix", 1999), ("abc", None), ("", None)])
def test_roman_numerals(text, value):
    assert _roman_to_int(text) == value
