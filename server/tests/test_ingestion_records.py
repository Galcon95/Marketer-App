"""How ingestion keeps a book's record in the database: status changes are saved, progress stays in memory, a book
deleted during processing stops it (and is not written back), and on startup the records come from the database.
No PDF is processed and no model is called."""

import pytest

from app.core import state as db
from app.core import storage
from app.core.schemas import Source
from app.db import records
from app.rag import ingestion


@pytest.fixture
def book(tmp_path, monkeypatch) -> Source:
    """A book being chunked, in memory and in the test database; no chunks, summaries or folders yet."""
    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(db, "sources", {})
    monkeypatch.setattr(db, "chunks", {})
    monkeypatch.setattr(db, "summaries", {})
    source = Source(id="src_a", project_id=db.DEFAULT_PROJECT_ID, filename="a.pdf", kind="document", size_bytes=1,
                    status="chunking", progress=0, chunk_count=0, created_at=db.now(), author="x", sha256="abc")
    records.add_source(source)
    db.sources[source.id] = source
    return source


def test_a_status_change_is_saved(book):
    ingestion._update(book.id, status="embedding", progress=0, chunk_count=12)
    saved = records.load_sources()[book.id]
    assert (saved.status, saved.chunk_count) == ("embedding", 12)


def test_progress_stays_in_memory(book):
    ingestion._update_progress(book.id, 40)
    assert db.sources[book.id].progress == 40
    assert records.load_sources()[book.id].progress == 0


def test_a_book_deleted_from_the_database_stops_the_processing(book):
    records.delete_source(book.id)
    with pytest.raises(ingestion._Cancelled):
        ingestion._update(book.id, status="ready")
    assert records.load_sources() == {}  # not written back


def test_on_startup_an_interrupted_book_is_marked_failed_in_the_database(book):
    db.sources.clear()
    ingestion.restore_sources()
    assert db.sources[book.id].status == "failed"
    assert "interrupted" in records.load_sources()[book.id].error


@pytest.mark.parametrize("key, status", [(None, "ready"), ("old-model--v1", "failed")])
def test_on_startup_a_ready_book_needs_chunks_of_the_current_model(book, key, status):
    from app.core.schemas import Chunk, ChunkLocation
    from app.rag import vectorstore
    records.update_source(book.model_copy(update={"status": "ready", "chunk_count": 1}))
    chunk = Chunk(id="chk_a_1", source_id=book.id, text="t", token_count=1, location=ChunkLocation())
    records.replace_chunks(book.project_id, book.id, [chunk], ["t"], [[1.0]], key or vectorstore.EMBEDDING_KEY)
    db.sources.clear()
    ingestion.restore_sources()
    assert db.sources[book.id].status == status
    assert ("chk_a_1" in db.chunks) == (status == "ready")
