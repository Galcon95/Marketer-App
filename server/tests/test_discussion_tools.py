"""Tools of the Discussion Relevance Agent (step 2): get_book_profile and search_book_material, bound to one run's
Research. A small made-up library is put into the in-memory state; the vector search is faked, so no API key is
needed and nothing is spent."""

from datetime import datetime, timezone

import pytest
from langchain_core.tools import ToolException

from app.agents import discussion_tools as dt
from app.core import state as db
from app.core.schemas import BookSummary, ChapterSummary, Chunk, ChunkLocation, Source

PROJECT = "test-project"
BOOK = "src_city"
TEXTS = {  # chunk id → (chapter, page, text)
    "chk_1": ("CHAPTER 3. THE ALGORITHMIC CITY", 41, "A city council can let AI propose bus routes, but people decide."),
    "chk_2": ("CHAPTER 3. THE ALGORITHMIC CITY", 44, "Every automated decision needs a named human who answers for it."),
    "chk_3": ("CHAPTER 7. TRUST", 102, "Citizens trust systems they can question."),
}


@pytest.fixture(autouse=True)
def library(monkeypatch):
    now = datetime.now(timezone.utc)

    def source(id_, filename, status="ready", project=PROJECT):
        return Source(id=id_, project_id=project, filename=filename, kind="document", size_bytes=1, status=status,
                      progress=100, chunk_count=3, created_at=now)

    monkeypatch.setattr(db, "sources", {
        BOOK: source(BOOK, "The-Human-AI-Civilization_Peter-Schmidt.pdf"),
        "src_busy": source("src_busy", "Still-Processing.pdf", status="embedding"),
        "src_other": source("src_other", "Someone-Elses-Book.pdf", project="other-project"),
    })
    monkeypatch.setattr(db, "chunks", {
        cid: Chunk(id=cid, source_id=BOOK, text=text, token_count=10, location=ChunkLocation(chapter=ch, page=page))
        for cid, (ch, page, text) in TEXTS.items()})
    monkeypatch.setattr(db, "summaries", {BOOK: BookSummary(
        source_id=BOOK, summary="How people and AI could share the running of societies.",
        themes=["AI in government", "accountability", "trust"], model="test", tokens=0, created_at=now,
        chapters=[ChapterSummary(chapter="CHAPTER 3. THE ALGORITHMIC CITY", first_page=40, last_page=60, summary="..."),
                  ChapterSummary(chapter=None, first_page=1, last_page=2, summary="...")])})
    monkeypatch.setattr(dt, "MIN_RELEVANCE", 0.3)


@pytest.fixture
def searches(monkeypatch):
    """Fake vector search: answers the next queued result and records each call's arguments."""
    calls, results = [], []

    def fake(project_id, query, k, source_ids=None, operation="search", where=None):
        calls.append({"project_id": project_id, "query": query, "k": k, "source_ids": source_ids,
                      "operation": operation})
        return [(db.chunks[cid], score) for cid, score in results.pop(0)]

    monkeypatch.setattr(dt, "retrieve_chunks", fake)
    return calls, results


def _tools(research):
    return {t.name: t for t in dt.make_tools(research)}


# ---------- start_research ----------
def test_research_starts_for_a_ready_book_of_the_project():
    research = dt.start_research(PROJECT, BOOK)
    assert (research.project_id, research.source_id, research.passages, research.queries) == (PROJECT, BOOK, [], [])


@pytest.mark.parametrize("source_id", ["src_unknown", "src_busy", "src_other"])
def test_research_refuses_unknown_unready_or_foreign_books(source_id):
    with pytest.raises(dt.BookNotReady):
        dt.start_research(PROJECT, source_id)


def test_the_model_sees_two_tools_without_a_book_argument():
    tools = dt.make_tools(dt.start_research(PROJECT, BOOK))
    assert [t.name for t in tools] == ["get_book_profile", "search_book_material"]
    assert tools[0].args == {}
    assert list(tools[1].args) == ["query"]
    assert "cite passage n as [n]" in tools[1].description


# ---------- get_book_profile ----------
def test_profile_has_title_author_overview_themes_and_chapters():
    research = dt.start_research(PROJECT, BOOK)
    profile = _tools(research)["get_book_profile"].invoke({})
    assert profile == {"title": "The Human AI Civilization", "author": "Peter Schmidt", "passages": 3,
                       "overview": "How people and AI could share the running of societies.",
                       "themes": ["AI in government", "accountability", "trust"],
                       "chapters": ["CHAPTER 3. THE ALGORITHMIC CITY"]}  # the untitled front section is left out
    assert research.profile_read


def test_profile_without_summary_says_to_search(monkeypatch):
    monkeypatch.setattr(db, "summaries", {})
    profile = _tools(dt.start_research(PROJECT, BOOK))["get_book_profile"].invoke({})
    assert profile["overview"] == "" and profile["themes"] == [] and "search the book directly" in profile["note"]


# ---------- search_book_material ----------
def test_search_only_looks_in_the_chosen_book(searches):
    calls, results = searches
    results.append([("chk_1", 0.71)])
    _tools(dt.start_research(PROJECT, BOOK))["search_book_material"].invoke({"query": "AI planning bus routes"})
    assert calls == [{"project_id": PROJECT, "query": "AI planning bus routes", "k": dt.SEARCH_K,
                      "source_ids": [BOOK], "operation": "discussion"}]


def test_search_returns_numbered_passages_and_drops_weak_ones(searches):
    _, results = searches
    results.append([("chk_1", 0.71), ("chk_2", 0.52), ("chk_3", 0.21)])
    research = dt.start_research(PROJECT, BOOK)
    result = _tools(research)["search_book_material"].invoke({"query": "AI in city government"})
    assert [(p["n"], p["page"], p["similarity"]) for p in result["passages"]] == [(1, 41, 0.71), (2, 44, 0.52)]
    assert result["passages"][0]["text"] == TEXTS["chk_1"][2]
    assert "note" not in result
    assert [c.id for c, _ in research.passages] == ["chk_1", "chk_2"]
    assert research.queries == ["AI in city government"]


def test_numbers_stay_the_same_across_searches(searches):
    _, results = searches
    results += [[("chk_1", 0.71), ("chk_2", 0.52)], [("chk_3", 0.66), ("chk_1", 0.48)]]
    research = dt.start_research(PROJECT, BOOK)
    search = _tools(research)["search_book_material"]
    search.invoke({"query": "AI in city government"})
    second = search.invoke({"query": "trust in automated decisions"})["passages"]
    assert second == [{"n": 3, "chapter": "CHAPTER 7. TRUST", "page": 102, "similarity": 0.66,
                       "text": TEXTS["chk_3"][2]},
                      {"n": 1, "chapter": "CHAPTER 3. THE ALGORITHMIC CITY", "page": 41, "similarity": 0.48,
                       "already_found": True}]  # found before: its number, no text again
    assert [c.id for c, _ in research.passages] == ["chk_1", "chk_2", "chk_3"]


def test_nothing_relevant_says_so_with_the_best_score(searches):
    _, results = searches
    results.append([("chk_3", 0.18), ("chk_1", 0.12)])
    research = dt.start_research(PROJECT, BOOK)
    result = _tools(research)["search_book_material"].invoke({"query": "sourdough bulk fermentation"})
    assert result["passages"] == []
    assert "best similarity 0.18, minimum 0.30" in result["note"]
    assert research.passages == [] and research.queries == ["sourdough bulk fermentation"]


def test_passages_stop_at_the_limit(searches, monkeypatch):
    monkeypatch.setattr(dt, "MAX_PASSAGES", 2)
    _, results = searches
    results.append([("chk_1", 0.71), ("chk_2", 0.52), ("chk_3", 0.5)])
    research = dt.start_research(PROJECT, BOOK)
    result = _tools(research)["search_book_material"].invoke({"query": "AI in city government"})
    assert [p["n"] for p in result["passages"]] == [1, 2]
    assert "limit of 2 passages" in result["note"]
    assert len(research.passages) == 2


@pytest.mark.parametrize("query", ["", "   ", "x" * 501])
def test_empty_or_too_long_queries_are_refused_without_a_search(searches, query):
    calls, _ = searches
    with pytest.raises(ToolException):
        dt.search_material(dt.start_research(PROJECT, BOOK), query)
    assert calls == []


def test_queries_are_cleaned_before_searching(searches):
    calls, results = searches
    results.append([("chk_1", 0.71)])
    research = dt.start_research(PROJECT, BOOK)
    result = dt.search_material(research, "  AI​ planning  ")
    assert calls[0]["query"] == result["query"] == research.queries[0]
    assert "​" not in calls[0]["query"]
