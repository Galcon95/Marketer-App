"""API tests of the upload checks: wrong file types and the duplicate check by content. Files go to a temporary
folder, the library starts empty and processing (chunking, embedding) is switched off, so nothing of the real
library is touched and no model is called."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import sources
from app.core import state as db
from app.core import storage
from app.rag import ingestion
from tests.conftest import sign_in

UPLOAD = "/projects/demo-campaign/sources"
PDF = b"%PDF-1.4\n% a tiny test file, not a real book\n"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A test client of the sources router with a temporary upload folder, an empty library and no processing."""
    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path)
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


def test_same_content_under_another_name_is_rejected_and_not_stored(client, tmp_path):
    assert _upload(client, "first.pdf", PDF).status_code == 201
    response = _upload(client, "renamed copy.pdf", PDF)
    assert response.status_code == 409
    assert "already in your library as 'first'" in response.json()["detail"]
    assert len(db.sources) == 1
    assert len(list(tmp_path.glob("*/*"))) == 1  # the rejected copy's folder was removed again


def test_different_content_is_accepted(client):
    assert _upload(client, "first.pdf", PDF).status_code == 201
    assert _upload(client, "second.pdf", PDF + b"other content").status_code == 201
    assert len(db.sources) == 2


def test_a_file_that_is_not_a_pdf_is_rejected(client):
    assert _upload(client, "fake.pdf", b"just text").status_code == 415
    assert _upload(client, "notes.txt", b"just text").status_code == 415


def test_an_uploaded_book_is_saved_in_the_database(client):
    from app.db import records
    source_id = _upload(client, "first.pdf", PDF).json()["id"]
    assert records.load_sources()[source_id].status == "queued"


def test_a_book_whose_record_cannot_be_saved_leaves_no_file(client, tmp_path, monkeypatch):
    from app.db import records
    from app.db.database import DatabaseError

    def broken(source):
        raise DatabaseError("Database error (OperationalError)")
    monkeypatch.setattr(records, "add_source", broken)
    assert _upload(client, "first.pdf", PDF).status_code == 500
    assert db.sources == {} and not any(tmp_path.glob("*/*/*.pdf"))
