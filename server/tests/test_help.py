"""The user manual (core/manual.py, api/help.py): served open as Markdown, its sections and anchors (the same rule as
the client's lib/markdown.ts anchor), and a manual that names only sections that exist in its own links."""

import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import help as help_api
from app.core import manual


def client() -> TestClient:
    app = FastAPI()
    app.include_router(help_api.open_router)
    return TestClient(app)


def test_the_manual_is_served_without_a_sign_in():
    response = client().get("/help/manual")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/markdown")
    assert "\n# Marketer App manual\n" in response.text


def test_a_missing_manual_answers_503(monkeypatch, tmp_path):
    monkeypatch.setattr(manual, "MANUAL_PATH", tmp_path / "missing.md")
    assert client().get("/help/manual").status_code == 503


def test_anchors_match_the_clients_rule():
    assert manual.anchor("Connect your YouTube channel") == "connect-your-youtube-channel"
    assert manual.anchor("Usage, limits & costs") == "usage-limits-costs"


def test_sections_are_the_level_2_and_3_headings():
    assert manual.sections("# T\n## Books\ntext\n### Upload a book\n#### deeper\n## Help") == [
        (2, "Books", "books"), (3, "Upload a book", "upload-a-book"), (2, "Help", "help")]


def test_every_link_inside_the_manual_points_to_a_section_that_exists():
    text = manual.text()
    anchors = {a for _, _, a in manual.sections(text)}
    targets = re.findall(r"\]\(#([a-z0-9-]+)\)", text)
    assert targets and not [t for t in targets if t not in anchors]
    assert len(anchors) == len(manual.sections(text)), "two sections have the same heading"
