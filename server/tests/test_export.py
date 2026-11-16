"""Export of assets as a file (GET /projects/{id}/assets/export, core/export.py): CSV with comma or semicolon,
Markdown; newest first; filtered by type and book; text without citation markers in CSV, with them in Markdown."""

import csv
import io
from datetime import timedelta

import pytest

from app.core import state as db
from app.core.schemas import ChunkLocation, Citation
from tests.test_ownership import NOW, OWNER, PROJECT, STRANGER, app, client_for  # noqa: F401  (app is a fixture)

URL = f"/projects/{PROJECT}/assets/export"


@pytest.fixture
def owner(app):  # noqa: F811
    """OWNER's client; besides ast_a (a blurb for all books) a newer grounded LinkedIn post for src_a with a citation."""
    db.assets["ast_post"] = db.assets["ast_a"].model_copy(update={
        "id": "ast_post", "asset_type": "social_post", "platform": "linkedin", "grounded": True, "source_ids": ["src_a"],
        "brief": "Why gardens", "text": "Cities need gardens [1] , says the book.\nAnd \"quotes\"; too.",
        "citations": [Citation(chunk_id="chk_1", source_id="src_a", location=ChunkLocation(chapter="Chapter 2", page=14),
                               quote="q", score=0.9)],
        "created_at": NOW + timedelta(minutes=5)})
    return client_for(app, OWNER)


def _rows(response) -> list[dict]:
    text = response.content.decode("utf-8")
    assert text.startswith("﻿")  # BOM: Excel reads UTF-8
    delimiter = ";" if text.splitlines()[0].count(";") > 3 else ","
    return list(csv.DictReader(io.StringIO(text[1:]), delimiter=delimiter))


def test_csv_lists_every_asset_newest_first_ready_to_post(owner):
    response = owner.get(URL)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="assets-' in response.headers["content-disposition"]
    rows = _rows(response)
    assert [r["id"] for r in rows] == ["ast_post", "ast_a"]
    post = rows[0]
    assert post["type"] == "Social post" and post["platform"] == "LinkedIn" and post["book"] == "a"
    assert post["text"] == "Cities need gardens, says the book.\nAnd \"quotes\"; too."  # markers gone, line kept
    assert post["sources"] == "[1] a, Chapter 2, p. 14"
    assert rows[1]["book"] == "All books" and rows[1]["sources"] == ""


def test_csv_for_excel_uses_semicolons(owner):
    rows = _rows(owner.get(URL, params={"format": "csv_semicolon"}))
    assert rows[0]["text"].startswith("Cities need gardens")  # the ";" inside the text is quoted, not a column break


def test_filters_by_type_and_book(owner):
    rows = _rows(owner.get(URL, params={"asset_type": "social_post", "source_id": "src_a"}))
    assert [r["id"] for r in rows] == ["ast_post"]
    assert "assets-social-post-" in owner.get(URL, params={"asset_type": "social_post"}).headers["content-disposition"]
    assert owner.get(URL, params={"asset_type": "newsletter"}).status_code == 404


def test_markdown_keeps_the_markers_and_lists_the_sources(owner):
    response = owner.get(URL, params={"format": "md"})
    assert response.headers["content-type"].startswith("text/markdown")
    text = response.text
    assert text.startswith("# Marketing assets (all types)\n\n2 assets")
    assert text.index("## Social post") < text.index("## Blurb")
    assert "Cities need gardens [1]" in text and "- [1] a, Chapter 2, p. 14" in text
    assert "**Brief:** Why gardens" in text and "LinkedIn" in text


def test_another_user_cannot_export(app):  # noqa: F811
    assert client_for(app, STRANGER).get(URL).status_code == 404
    assert client_for(app, OWNER).get(URL, params={"format": "pdf"}).status_code == 422
