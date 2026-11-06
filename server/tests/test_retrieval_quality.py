"""Retrieval quality controls without a model or vector store: the contextual chunk header, the relevance floor with
its "not covered" answer, BM25 keyword search and the hybrid fusion. A small made-up library is put into the
in-memory state for each test (and removed again)."""

from datetime import datetime, timezone

import pytest

from app.core import state as db
from app.core.schemas import Chunk, ChunkLocation, Source
from app.rag import keyword, qa, retrieval, vectorstore

PROJECT = "test-project"
TEXTS = {  # chunk id → (source id, chapter, page, text)
    "chk_1": ("src_stock", "CHAPTER V. BUCKET SHOPS", 30, "A bucket shop takes orders but never buys the stock."),
    "chk_2": ("src_stock", "CHAPTER XX. PUTS AND CALLS", 80, "A put is the right to sell a stock at a fixed price."),
    "chk_3": ("src_garden", "CHAPTER IV. THE REVENUE", 40, "The rate-rent pays interest and builds the town."),
}


@pytest.fixture(autouse=True)
def library(monkeypatch):
    now = datetime.now(timezone.utc)
    sources = {
        "src_stock": Source(id="src_stock", project_id=PROJECT, filename="Successful Stock Speculation.pdf",
                            kind="document", size_bytes=1, status="ready", progress=100, chunk_count=2, created_at=now),
        "src_garden": Source(id="src_garden", project_id=PROJECT, filename="Garden-Cities_Ebenezer-Howard.pdf",
                             kind="document", size_bytes=1, status="ready", progress=100, chunk_count=1, created_at=now),
    }
    chunks = {cid: Chunk(id=cid, source_id=src, text=text, token_count=10, location=ChunkLocation(chapter=ch, page=page))
              for cid, (src, ch, page, text) in TEXTS.items()}
    monkeypatch.setattr(db, "sources", sources)
    monkeypatch.setattr(db, "chunks", chunks)


# ---------- contextual chunk header ----------
def test_chunks_are_embedded_with_book_and_chapter():
    doc = vectorstore._to_document(db.chunks["chk_1"], "Successful Stock Speculation")
    assert doc.page_content == ("Successful Stock Speculation · CHAPTER V. BUCKET SHOPS\n\n"
                                "A bucket shop takes orders but never buys the stock.")
    assert doc.metadata["chapter"] == "CHAPTER V. BUCKET SHOPS"  # the filters still work on metadata


def test_a_chunk_without_book_or_chapter_is_embedded_as_it_is():
    chunk = Chunk(id="c", source_id="s", text="Plain.", token_count=1, location=ChunkLocation())
    assert vectorstore._to_document(chunk).page_content == "Plain."


def test_the_collection_name_contains_the_index_format(monkeypatch):
    """A new INDEX_FORMAT means a new collection, so old vectors are never mixed with new ones."""
    monkeypatch.setattr(vectorstore, "Chroma", lambda **options: options)
    monkeypatch.setattr(vectorstore, "_client", lambda: None)
    options = vectorstore._store.__wrapped__(PROJECT)
    assert options["collection_name"] == f"{PROJECT}--text-embedding-3-large--{vectorstore.INDEX_FORMAT}"
    assert options["collection_configuration"]["hnsw"]["max_neighbors"] > 16  # better recall than Chroma's default


# ---------- relevance floor ----------
@pytest.fixture(autouse=True)
def no_filter_extraction(monkeypatch):
    monkeypatch.setattr(qa, "might_filter", lambda project_id, question: False)


def _fake_search(scores):
    return lambda project_id, query, k, source_ids=None, operation="search", where=None: [
        (db.chunks[cid], s) for cid, s in scores]


def test_passages_below_the_floor_are_dropped(monkeypatch):
    monkeypatch.setattr(qa, "MIN_RELEVANCE", 0.3)
    monkeypatch.setattr(qa, "retrieve_chunks", _fake_search([("chk_1", 0.62), ("chk_2", 0.31), ("chk_3", 0.12)]))
    state = qa._retrieve({"project_id": PROJECT, "question": "What is a bucket shop?", "k": 3})
    assert [c.id for c, _ in state["context"]] == ["chk_1", "chk_2"]


def test_an_off_topic_question_gets_a_fixed_answer_without_a_model_call(monkeypatch):
    monkeypatch.setattr(qa, "MIN_RELEVANCE", 0.3)
    monkeypatch.setattr(qa, "retrieve_chunks", _fake_search([("chk_1", 0.22), ("chk_3", 0.18)]))
    monkeypatch.setattr(qa, "chat_model", lambda *a, **kw: pytest.fail("no model call expected"))
    state = qa._graph().invoke({"project_id": PROJECT, "question": "How do I bake bread?", "k": 2, "history": []})
    assert state["answer"].startswith("The books don't cover this")
    assert "Successful Stock Speculation" in state["answer"] and "Garden Cities" in state["answer"]
    assert state["citations"] == [] and state["context"] == [] and state["tokens"] == 0
    assert "no passage was relevant enough (best similarity 0.22" in state["filter_note"]


def test_with_tools_the_model_still_answers_without_passages(monkeypatch):
    """"Which books do you have?" matches no passage, but list_books can answer it."""
    monkeypatch.setattr(qa, "MIN_RELEVANCE", 0.3)
    monkeypatch.setattr(qa, "retrieve_chunks", _fake_search([("chk_1", 0.2)]))
    seen = {}

    def fake_invoke(messages, tools=None, final=False):
        seen["prompt"] = messages[-1].content
        return None, qa.QAAnswer(answer="Two books.", used_sources=[]), 5

    monkeypatch.setattr(qa, "_invoke_answer", fake_invoke)
    monkeypatch.setattr(qa, "make_tools", lambda project_id: [])
    state = qa._graph().invoke({"project_id": PROJECT, "question": "Which books do you have?", "k": 2, "history": [],
                                "use_tools": True})
    assert state["answer"] == "Two books."
    assert "(none: no passage is close enough to the question)" in seen["prompt"]


# ---------- keyword search (BM25) ----------
def test_keyword_search_ranks_exact_terms():
    assert keyword.search(PROJECT, "What is the rate-rent?", 3) == ["chk_3"]
    assert keyword.search(PROJECT, "bucket shop", 3)[0] == "chk_1"


def test_keyword_search_respects_book_chapter_and_page_filters():
    assert keyword.search(PROJECT, "stock", 3, source_ids=["src_garden"]) == []
    assert keyword.search(PROJECT, "stock", 3, where={"chapter": {"$in": ["CHAPTER XX. PUTS AND CALLS"]}}) == ["chk_2"]
    assert keyword.search(PROJECT, "stock", 3, where={"$and": [{"page": {"$gte": 50}}, {"page": {"$lte": 90}}]}) == ["chk_2"]


def test_keyword_search_ignores_other_projects():
    assert keyword.search("other-project", "bucket shop", 3) == []


def test_the_keyword_index_follows_new_chunks(monkeypatch):
    keyword.search(PROJECT, "bucket", 3)
    chunks = dict(db.chunks)
    chunks["chk_4"] = Chunk(id="chk_4", source_id="src_garden", text="Allotments and orchards.", token_count=3,
                            location=ChunkLocation(chapter="CHAPTER I.", page=5))
    monkeypatch.setattr(db, "chunks", chunks)
    assert keyword.search(PROJECT, "orchards", 3) == ["chk_4"]


# ---------- hybrid: reciprocal rank fusion, scores stay cosine similarities ----------
def test_hybrid_fuses_both_rankings_and_keeps_cosine_scores(monkeypatch):
    monkeypatch.setattr(retrieval, "RETRIEVAL_MODE", "hybrid")
    monkeypatch.setattr(retrieval.vectorstore, "search",
                        lambda project_id, query, k, source_ids=None, operation="search", where=None:
                        [("chk_2", 0.5), ("chk_1", 0.45)])
    monkeypatch.setattr(retrieval.keyword, "search", lambda project_id, query, n, source_ids=None, where=None:
                        ["chk_1", "chk_3"])
    looked_up = []
    monkeypatch.setattr(retrieval.vectorstore, "similarities",
                        lambda project_id, query, ids, operation="search": looked_up.extend(ids) or {i: 0.33 for i in ids})
    hits = retrieval.retrieve_chunks(PROJECT, "bucket shop", 3)
    assert [(c.id, s) for c, s in hits] == [("chk_1", 0.45), ("chk_2", 0.5), ("chk_3", 0.33)]  # chk_1 is in both
    assert looked_up == ["chk_3"]  # only the keyword-only hit needs its similarity looked up
