"""API tests of the upload checks: wrong file types and the duplicate check by content. Files go to a temporary
folder, the library starts empty and processing (chunking, embedding) is switched off, so nothing of the real
library is touched and no model is called."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import sources
from app.core import state as db
from app.rag import ingestion
from tests.conftest import sign_in

UPLOAD = "/projects/demo-campaign/sources"
PDF = b"%PDF-1.4\n% a tiny test file, not a real book\n"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A test client of the sources router with a temporary upload folder, an empty library and no processing."""
    monkeypatch.setattr(db, "sources", {})
    monkeypatch.setattr(ingestion, "ingest_source", lambda source_id: None)
    app = FastAPI()
    app.include_router(sources.router)
    sign_in(app)
    with TestClient(app) as test_client:
        yield test_client


def _upload(client: TestClient, name: str, content: bytes):
    return client.post(UPLOAD, files={"file": (name, content, "application/pdf")})


def test_upload_records_the_content_checksum(client):
    response = _upload(client, "first.pdf", PDF)
    assert response.status_code == 201
    assert len(response.json()["sha256"]) == 64


def test_same_content_under_another_name_is_rejected_and_not_stored(client, stored_files):
    assert _upload(client, "first.pdf", PDF).status_code == 201
    response = _upload(client, "renamed copy.pdf", PDF)
    assert response.status_code == 409
    assert "already in your library as 'first'" in response.json()["detail"]
    assert len(db.sources) == 1
    assert len(stored_files.objects) == 1  # the rejected copy was never stored


def test_different_content_is_accepted(client):
    assert _upload(client, "first.pdf", PDF).status_code == 201
    assert _upload(client, "second.pdf", PDF + b"other content").status_code == 201
    assert len(db.sources) == 2


def test_a_file_that_is_not_a_pdf_is_rejected(client):
    assert _upload(client, "fake.pdf", b"just text").status_code == 415
    assert _upload(client, "notes.txt", b"just text").status_code == 415


def test_an_uploaded_book_is_saved_in_the_database_and_storage(client, stored_files):
    from app.db import records
    source_id = _upload(client, "first.pdf", PDF).json()["id"]
    assert records.load_sources()[source_id].status == "queued"
    assert stored_files.objects == {f"demo-campaign/{source_id}/book.pdf": PDF}
    file = client.get(f"/sources/{source_id}/file")  # streamed back for the browser's PDF viewer
    assert (file.status_code, file.content, file.headers["content-type"]) == (200, PDF, "application/pdf")
    assert file.headers["content-disposition"] == "inline; filename*=UTF-8''first.pdf"


def test_a_book_whose_record_cannot_be_saved_leaves_no_file(client, stored_files, monkeypatch):
    from app.db import records
    from app.db.database import DatabaseError

    def broken(source):
        raise DatabaseError("Database error (OperationalError)")
    monkeypatch.setattr(records, "add_source", broken)
    assert _upload(client, "first.pdf", PDF).status_code == 500
    assert db.sources == {} and stored_files.objects == {}  # the stored file was removed again


def test_a_book_that_cannot_be_stored_is_not_saved(client, monkeypatch):
    from app.core import files
    from app.db import records

    def broken(path, data, content_type):
        raise files.FileStoreError("Storage cannot be reached")
    monkeypatch.setattr(files, "put", broken)
    assert _upload(client, "first.pdf", PDF).status_code == 500
    assert db.sources == {} and records.load_sources() == {}


def test_no_temporary_file_is_left_behind(client, monkeypatch, tmp_path):
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    _upload(client, "first.pdf", PDF)
    _upload(client, "first.pdf", PDF)  # rejected as a duplicate
    _upload(client, "fake.pdf", b"just text")  # rejected as not a PDF
    assert list(tmp_path.iterdir()) == []


def test_a_missing_file_is_404(client):
    source_id = _upload(client, "first.pdf", PDF).json()["id"]
    from app.core import files
    files.delete_source_files("demo-campaign", source_id)
    assert client.get(f"/sources/{source_id}/file").status_code == 404


def test_a_book_over_the_storage_limit_is_rejected_with_advice(client, stored_files, monkeypatch):
    from app.core import storage
    monkeypatch.setattr(storage, "MAX_UPLOAD_BYTES", 16)  # stands for the 50 MB of Supabase Storage
    response = _upload(client, "big.pdf", PDF)
    assert response.status_code == 413
    detail = response.json()["detail"]
    assert "Supabase" in detail and "compress" in detail and "split it into parts" in detail
    assert db.sources == {}
