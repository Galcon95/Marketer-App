"""Listing campaign kits page by page (GET /projects/{id}/campaigns), loading one kit
(GET .../campaigns/{campaign_id}) and the filters of GET /projects/{id}/assets: the Campaign kit tab loads summaries
first and a kit's texts only when it is opened, so many kits stay fast."""

from datetime import timedelta

import pytest

from app.core import state as db
from tests.test_ownership import NOW, OWNER, PROJECT, app, client_for  # noqa: F401  (app is a fixture)


@pytest.fixture
def owner(app):  # noqa: F811
    """OWNER's client with 12 kits of 3 assets (cmp_00 oldest ... cmp_11 newest) next to ast_a (in cmp_a, older)."""
    base = db.assets["ast_a"]
    for k in range(12):
        for i, kind in enumerate(("persona", "social_post", "blurb")):
            asset_id = f"ast_{k:02}_{i}"
            db.assets[asset_id] = base.model_copy(update={
                "id": asset_id, "asset_type": kind, "campaign_id": f"cmp_{k:02}", "tokens": 10,
                "brief": f'Book: "Book {k}" by Someone\nPremise: P', "source_ids": ["src_a"],
                "created_at": NOW + timedelta(minutes=k + 1, microseconds=i)})
    return client_for(app, OWNER)


def test_campaigns_come_newest_first_page_by_page(owner):
    first = owner.get(f"/projects/{PROJECT}/campaigns", params={"limit": 5}).json()
    assert first["total"] == 13  # 12 kits + cmp_a
    assert [c["campaign_id"] for c in first["items"]] == ["cmp_11", "cmp_10", "cmp_09", "cmp_08", "cmp_07"]
    row = first["items"][0]
    assert row["title"] == "Book 11" and row["asset_count"] == 3 and row["tokens"] == 30
    assert row["source_id"] == "src_a" and "text" not in row  # a summary, not the assets
    last = owner.get(f"/projects/{PROJECT}/campaigns", params={"limit": 5, "offset": 10}).json()
    assert [c["campaign_id"] for c in last["items"]] == ["cmp_01", "cmp_00", "cmp_a"]
    assert last["items"][-1]["title"] == "Campaign"  # a brief without 'Book: "..."'


def test_one_campaign_loads_its_assets_in_order(owner):
    kit = owner.get(f"/projects/{PROJECT}/campaigns/cmp_03").json()
    assert [a["id"] for a in kit] == ["ast_03_0", "ast_03_1", "ast_03_2"]
    assert owner.get(f"/projects/{PROJECT}/campaigns/cmp_nope").status_code == 404


def test_page_size_is_limited(owner):
    assert owner.get(f"/projects/{PROJECT}/campaigns", params={"limit": 0}).status_code == 422
    assert owner.get(f"/projects/{PROJECT}/campaigns", params={"limit": 101}).status_code == 422


def test_assets_can_be_filtered(owner):
    db.assets["ast_single"] = db.assets["ast_a"].model_copy(update={"id": "ast_single", "campaign_id": "",
                                                                    "created_at": NOW + timedelta(hours=1)})
    url = f"/projects/{PROJECT}/assets"
    personas = owner.get(url, params={"asset_type": "persona", "source_id": "src_a"}).json()
    assert len(personas) == 12 and all(a["asset_type"] == "persona" for a in personas)
    singles = owner.get(url, params={"grounded": "false", "in_campaign": "false"}).json()
    assert [a["id"] for a in singles] == ["ast_single"]
    assert len(owner.get(url).json()) == 38  # no filter: everything, as before
    assert [a["id"] for a in owner.get(url, params={"limit": 2}).json()] == ["ast_11_2", "ast_single"]
