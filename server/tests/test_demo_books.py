"""Tests of the demo's books (core/demo_books.py): a ready book is copied into the guest's project with its file,
cover, summary and chunks with embeddings (nothing embedded again); a second run skips it; a failed copy leaves
nothing behind; the original is never touched."""

from datetime import datetime, timezone

import pytest

from app.core import demo_books, files
from app.core import state as db
from app.core.schemas import BookSummary, Chunk, ChunkLocation, Project, Source
from app.db import records

NOW = datetime.now(timezone.utc)
ORIGINAL = Source(id="src_orig", project_id=db.DEFAULT_PROJECT_ID, filename="Old-Book.pdf", kind="document",
                  size_bytes=10, status="ready", progress=100, chunk_count=3, created_at=NOW, author="A. Author",
                  sha256="abc")


@pytest.fixture
def guest_project() -> Project:
    project = Project(id="prj_guest", name="guest@demo.example", description="", created_at=NOW, owner_id="user-guest")
    records.save_project(project)
    return project


@pytest.fixture
def original(stored_files):
    records.add_source(ORIGINAL)
    chunks = [Chunk(id=f"chk_orig_{n:04d}", source_id="src_orig", text=f"Text {n}.", token_count=3,
                    location=ChunkLocation(chapter="I", page=n)) for n in range(1, 4)]
    records.replace_chunks(db.DEFAULT_PROJECT_ID, "src_orig", chunks, [f"Old Book · I\n\nText {n}." for n in range(1, 4)],
                           [[1.0, 0.0], [0.0, 1.0], [0.6, 0.8]], "model--v2")
    records.save_summary(BookSummary(source_id="src_orig", summary="About old things.", themes=["t"], chapters=[],
                                     model="m", tokens=5, created_at=NOW))
    stored_files.objects[f"{db.DEFAULT_PROJECT_ID}/src_orig/book.pdf"] = b"%PDF"
    stored_files.objects[f"{db.DEFAULT_PROJECT_ID}/src_orig/cover.png"] = b"PNG"
    return ORIGINAL


def test_a_book_is_copied_with_everything(original, guest_project, stored_files):
    copy = demo_books.copy_book(original, guest_project)
    assert copy is not None and copy.id != original.id and copy.project_id == "prj_guest"
    assert (copy.filename, copy.author, copy.chunk_count, copy.status) == ("Old-Book.pdf", "A. Author", 3, "ready")
    assert records.load_sources()[copy.id] == copy
    assert stored_files.objects[f"prj_guest/{copy.id}/book.pdf"] == b"%PDF"
    assert stored_files.objects[f"prj_guest/{copy.id}/cover.png"] == b"PNG"
    assert records.load_summaries()[copy.id].summary == "About old things."
    chunks = records.load_chunks()[copy.id]
    prefix = copy.id.removeprefix("src_")
    assert [c.id for c in chunks] == [f"chk_{prefix}_{n:04d}" for n in range(1, 4)]
    assert [c.location.page for c in chunks] == [1, 2, 3]
    assert records.chunk_embeddings([f"chk_{prefix}_0003"]) == {f"chk_{prefix}_0003": pytest.approx([0.6, 0.8])}
    assert records.chunk_counts("model--v2") == {"src_orig": 3, copy.id: 3}  # searchable as they are
    assert len(records.load_chunks()["src_orig"]) == 3  # the original keeps its own


def test_a_second_run_skips_the_book(original, guest_project):
    assert demo_books.copy_book(original, guest_project) is not None
    assert demo_books.copy_book(original, guest_project) is None
    assert sum(s.project_id == "prj_guest" for s in records.load_sources().values()) == 1


def test_only_ready_books_are_copied(original, guest_project):
    with pytest.raises(ValueError):
        demo_books.copy_book(original.model_copy(update={"status": "failed"}), guest_project)


def test_a_failed_copy_leaves_nothing_behind(original, guest_project, stored_files, monkeypatch):
    def broken(*args):
        raise OSError("Database error")
    monkeypatch.setattr(records, "copy_chunks", broken)
    with pytest.raises(OSError):
        demo_books.copy_book(original, guest_project)
    assert [s.id for s in records.load_sources().values()] == ["src_orig"]
    assert all(not path.startswith("prj_guest/") for path in stored_files.objects)
    assert set(records.load_summaries()) == {"src_orig"}


def test_a_book_without_its_file_is_not_copied(original, guest_project, stored_files):
    del stored_files.objects[f"{db.DEFAULT_PROJECT_ID}/src_orig/book.pdf"]
    with pytest.raises(FileNotFoundError):
        demo_books.copy_book(original, guest_project)
    assert [s.id for s in records.load_sources().values()] == ["src_orig"]


def test_a_large_book_on_the_servers_disk_is_copied_there(original, guest_project, stored_files):
    del stored_files.objects[f"{db.DEFAULT_PROJECT_ID}/src_orig/book.pdf"]
    files.put(f"{db.DEFAULT_PROJECT_ID}/src_orig/book.pdf", b"%PDF big", "application/pdf", on_server=True)
    copy = demo_books.copy_book(original, guest_project)
    assert files._server.get(f"prj_guest/{copy.id}/book.pdf") == b"%PDF big"
    assert f"prj_guest/{copy.id}/book.pdf" not in stored_files.objects
