"""What a model call was for (usage.tagged): every call recorded inside the context gets the book, asset and
campaign; a single asset stores the cost of its calls; a campaign row shows the cost of its kit."""

from datetime import datetime, timezone

import pytest

from app.core import state as db
from app.core import usage
from app.core.schemas import GenerateRequest, UsageRecord
from app.db import records
from app.rag import generation
from tests.test_ownership import OWNER, PROJECT, app, client_for  # noqa: F401  (app is a fixture)


def _call(cost: float = 0.001, **fields) -> UsageRecord:
    return UsageRecord(timestamp=datetime.now(timezone.utc), operation="op", kind="chat", model="m", input_tokens=1,
                       output_tokens=1, input_cost=cost, output_cost=0.0, cost=cost, cost_source="estimate", **fields)


def _latest() -> UsageRecord:
    return records.recent_usage(1)[0]


def test_calls_inside_the_context_get_its_tags():
    with usage.tagged(asset_id="ast_1", asset_type="newsletter", source_id="src_1"):
        usage.record(_call())
        assert (_latest().asset_id, _latest().asset_type, _latest().source_id) == ("ast_1", "newsletter", "src_1")
        with usage.tagged(source_id="src_2", campaign_id=None):  # nested: overrides, None is left out
            usage.record(_call())
            assert (_latest().asset_id, _latest().source_id, _latest().campaign_id) == ("ast_1", "src_2", None)
        usage.record(_call(source_id="src_own"))  # a field the call sets itself wins
        assert _latest().source_id == "src_own"
    usage.record(_call())
    assert (_latest().asset_id, _latest().source_id) == (None, None)  # outside: nothing


def test_unknown_tags_are_refused():
    with pytest.raises(ValueError):
        with usage.tagged(book="src_1"):
            pass


def test_a_single_asset_stores_the_cost_of_its_calls(app, monkeypatch):  # noqa: F811
    def fake_generate(project_id, req):  # two model calls, as the graph would make them
        usage.record(_call(0.002))
        usage.record(_call(0.0005))
        return {"text": "A text.", "tokens": 10}

    monkeypatch.setattr(generation, "generate_asset", fake_generate)
    usage.record(_call(0.1))  # another call, not part of the asset
    asset = generation.create_asset(PROJECT, GenerateRequest(asset_type="newsletter", brief="b", source_ids=["src_a"]))
    assert asset.cost == pytest.approx(0.0025)
    tagged = [r for r in records.recent_usage(10) if r.asset_id == asset.id]
    assert len(tagged) == 2 and {(r.asset_type, r.source_id) for r in tagged} == {("newsletter", "src_a")}
    assert records.load_assets()[asset.id].cost == pytest.approx(0.0025)  # saved with the asset


def test_an_asset_for_several_books_counts_for_no_single_book(app, monkeypatch):  # noqa: F811
    monkeypatch.setattr(generation, "generate_asset", lambda project_id, req: usage.record(_call()) or {"text": "T"})
    generation.create_asset(PROJECT, GenerateRequest(asset_type="blurb", brief="b", source_ids=["src_a", "src_b"]))
    assert _latest().source_id is None and _latest().asset_type == "blurb"


def test_campaign_rows_show_the_cost_of_their_kit(app):  # noqa: F811
    db.assets["ast_a"] = db.assets["ast_a"].model_copy(update={"campaign_id": "cmp_a"})
    db.assets["ast_old"] = db.assets["ast_a"].model_copy(update={"id": "ast_old", "campaign_id": "cmp_old"})
    with usage.tagged(campaign_id="cmp_a"):
        usage.record(_call(0.003))
        usage.record(_call(0.001))
    rows = client_for(app, OWNER).get(f"/projects/{PROJECT}/campaigns").json()["items"]
    costs = {r["campaign_id"]: r["cost"] for r in rows}
    assert costs["cmp_a"] == pytest.approx(0.004) and costs["cmp_old"] is None  # older kits: not recorded
