"""API tests of deleting a book: everything that belongs only to it goes (files, chunks, summary, assets made only
from it, chats that only used its passages); what also draws on other books stays. Storage goes to a temporary
folder, the library is made up for each test and the vector store is switched off, so nothing real is touched."""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import sources
from app.core import state as db
from app.core import storage
from app.core.schemas import Asset, ChatTurn, Chunk, ChunkLocation, Conversation, SearchHit, Source
from app.rag import vectorstore

PROJECT = "demo-campaign"
NOW = datetime.now(timezone.utc)


def _source(source_id: str) -> Source:
    return Source(id=source_id, project_id=PROJECT, filename=f"{source_id}.pdf", kind="document", size_bytes=1,
                  status="ready", progress=100, chunk_count=1, created_at=NOW)


def _asset(asset_id: str, source_ids: list[str]) -> Asset:
    return Asset(id=asset_id, project_id=PROJECT, asset_type="blurb", grounded=True, brief="b", text="t",
                 citations=[], created_at=NOW, source_ids=source_ids)


def _chat(conversation_id: str, passage_sources: list[str]) -> Conversation:
    """A chat with one turn whose retrieved passages come from the given books."""
    hits = [SearchHit(chunk=Chunk(id=f"chk_{i}", source_id=s, text="x", location=ChunkLocation(), token_count=1), score=0.5)
            for i, s in enumerate(passage_sources)]
    turn = ChatTurn(question="q", search_query="q", answer="a", citations=[], passages=hits, model="m", tokens=1,
                    created_at=NOW)
    return Conversation(id=conversation_id, project_id=PROJECT, title="q", created_at=NOW, updated_at=NOW, turns=[turn])


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Two books (src_a, src_b) with assets and chats; storage in tmp_path; no vector store."""
    for name in ("UPLOAD_DIR", "GENERATED_DIR", "CONVERSATIONS_DIR"):
        monkeypatch.setattr(storage, name, tmp_path / name.lower())
    monkeypatch.setattr(vectorstore, "delete_source", lambda project_id, source_id: None)
    monkeypatch.setattr(db, "sources", {s: _source(s) for s in ("src_a", "src_b")})
    monkeypatch.setattr(db, "chunks", {})
    monkeypatch.setattr(db, "summaries", {})
    monkeypatch.setattr(db, "assets", {a.id: a for a in [
        _asset("ast_only_a", ["src_a"]),  # made only from book A → deleted with it
        _asset("ast_a_and_b", ["src_a", "src_b"]),  # also draws on book B → kept
        _asset("ast_all_books", []),  # "all books" → kept
        _asset("ast_only_b", ["src_b"]),  # another book → kept
    ]})
    monkeypatch.setattr(db, "conversations", {c.id: c for c in [
        _chat("cnv_only_a", ["src_a", "src_a"]),  # only A's passages → deleted
        _chat("cnv_mixed", ["src_a", "src_b"]),  # also B's passages → kept
    ]})
    (tmp_path / "upload_dir" / PROJECT / "src_a").mkdir(parents=True)
    app = FastAPI()
    app.include_router(sources.router)
    with TestClient(app) as test_client:
        yield test_client


def test_preview_counts_what_would_go_without_deleting(client):
    response = client.get("/sources/src_a/deletion")
    assert response.status_code == 200
    assert (response.json()["assets"], response.json()["conversations"]) == (1, 1)
    assert "src_a" in db.sources and "ast_only_a" in db.assets


def test_delete_removes_the_book_and_only_what_belongs_to_it_alone(client, tmp_path):
    response = client.delete("/sources/src_a")
    assert response.status_code == 200
    assert (response.json()["assets"], response.json()["conversations"]) == (1, 1)
    assert set(db.sources) == {"src_b"}
    assert set(db.assets) == {"ast_a_and_b", "ast_all_books", "ast_only_b"}
    assert set(db.conversations) == {"cnv_mixed"}
    assert not (tmp_path / "upload_dir" / PROJECT / "src_a").exists()


def test_unknown_book_is_404(client):
    assert client.get("/sources/nope/deletion").status_code == 404
    assert client.delete("/sources/nope").status_code == 404
