"""Tests of the database layer (app/db) on the in-memory test database of conftest.py: projects, assets and chats
saved and loaded, one project per owner, a kit saved in one transaction, the one-time import of the old JSON files,
and the connection settings."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.core import config, usage
from app.core import state as db
from app.core.schemas import (Asset, ChatTurn, Chunk, ChunkLocation, Citation, Conversation, Project,
                              SearchHit, UsageRecord, UsageTotals)
from app.db import database, import_files, records
from app.db.database import DatabaseError
from app.db.tables import AssetRow, ConversationRow
from tests.conftest import OWNER, STRANGER


def _project(id: str, owner_id: str = "") -> Project:
    return Project(id=id, name=id, description="", created_at=db.now(), owner_id=owner_id)


def test_a_project_is_saved_and_loaded_with_its_owner():
    records.save_project(_project("prj_1", STRANGER.id))
    loaded = records.load_projects()["prj_1"]
    assert (loaded.owner_id, loaded.created_at.tzinfo is not None) == (STRANGER.id, True)


def test_a_project_without_owner_stays_without_owner_and_can_be_claimed():
    records.save_project(_project("prj_1"))
    assert records.load_projects()["prj_1"].owner_id == ""
    records.save_project(_project("prj_1", STRANGER.id))  # the same id: updated, not added
    assert records.load_projects()["prj_1"].owner_id == STRANGER.id


def test_counts_are_not_stored():
    records.save_project(_project("prj_1").model_copy(update={"source_count": 7}))
    assert records.load_projects()["prj_1"].source_count == 0


def test_nobody_owns_two_projects():
    """The unique owner_id: also two requests at once cannot give a user a second project."""
    with pytest.raises(DatabaseError):
        records.save_project(_project("prj_second", OWNER.id))  # OWNER already owns the default project (conftest)


def test_projects_without_owner_can_be_many():
    records.save_project(_project("prj_1"))
    records.save_project(_project("prj_2"))
    assert {"prj_1", "prj_2"} <= set(records.load_projects())


# ---------- One-time import of the JSON files ----------

def test_the_import_adds_new_records_once_and_keeps_existing_ones(tmp_path):
    projects_file, keys_file = tmp_path / "projects.json", tmp_path / "api_keys.json"
    projects_file.write_text(json.dumps([
        {"id": db.DEFAULT_PROJECT_ID, "name": "From the file", "description": "", "created_at": "2026-11-05T08:35:01Z",
         "owner_id": "someone-else"},  # already in the database: not overwritten
        {"id": "prj_4b1c3ebd", "name": "a@example.com", "description": "", "created_at": "2026-11-05T09:39:52Z",
         "owner_id": STRANGER.id},
    ]), encoding="utf-8")
    keys_file.write_text(json.dumps([
        {"id": "key_1", "user_id": OWNER.id, "email": OWNER.email, "name": "Claude Desktop", "shown": "mk_abcdefgh",
         "key_hash": "0" * 64, "created_at": "2026-11-05T12:36:13Z", "last_used_at": None},
    ]), encoding="utf-8")

    assert (import_files.import_projects(projects_file), import_files.import_api_keys(keys_file)) == (1, 1)
    assert (import_files.import_projects(projects_file), import_files.import_api_keys(keys_file)) == (0, 0)
    loaded = records.load_projects()
    assert loaded[db.DEFAULT_PROJECT_ID].owner_id == OWNER.id
    assert loaded["prj_4b1c3ebd"].owner_id == STRANGER.id
    assert [k.id for k in records.load_api_keys()] == ["key_1"]


def test_the_import_without_files_imports_nothing(tmp_path):
    assert import_files.import_projects(tmp_path / "missing.json") == 0
    assert import_files.import_api_keys(tmp_path / "missing.json") == 0


# ---------- Connection settings ----------

@pytest.mark.parametrize("url, expected", [
    ("postgresql://u:p@host:5432/postgres", "postgresql+psycopg://u:p@host:5432/postgres"),
    ("postgres://u:p@host:5432/postgres", "postgresql+psycopg://u:p@host:5432/postgres"),
    ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
    ("sqlite://", "sqlite://"),
])
def test_the_supabase_connection_string_gets_the_psycopg_driver(url, expected):
    assert config._sqlalchemy_url(url) == expected


def test_without_database_url_nothing_can_be_read(monkeypatch):
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "DATABASE_URL", "")
    with pytest.raises(DatabaseError, match="DATABASE_URL"):
        records.load_projects()


# ---------- Generated assets and conversations ----------

def _asset(asset_id: str, **changes) -> Asset:
    citation = Citation(chunk_id="chk_1", source_id="src_a", location=ChunkLocation(chapter="1", page=3),
                        quote="q", score=0.8)
    asset = Asset(id=asset_id, project_id=db.DEFAULT_PROJECT_ID, asset_type="social_post", grounded=True, brief="b",
                  text="t [1]", citations=[citation], created_at=db.now(), platform="linkedin",
                  source_ids=["src_a"], ai_tells=["delve"], campaign_id="cmp_1", model="m", persona="Anna")
    return asset.model_copy(update=changes)


def _conversation(conversation_id: str) -> Conversation:
    hit = SearchHit(chunk=Chunk(id="chk_1", source_id="src_a", text="x", location=ChunkLocation(page=2),
                                token_count=1), score=0.5)
    turn = ChatTurn(question="q", search_query="q", answer="a", citations=[], passages=[hit], model="m", tokens=1,
                    created_at=db.now())
    return Conversation(id=conversation_id, project_id=db.DEFAULT_PROJECT_ID, title="q", created_at=db.now(),
                        updated_at=db.now(), turns=[turn])


def test_every_asset_field_has_a_column():
    """A new field in schemas.Asset needs a column (and a migration), or it would be lost on save."""
    assert set(AssetRow.__table__.columns.keys()) == set(Asset.model_fields)
    assert set(ConversationRow.__table__.columns.keys()) == set(Conversation.model_fields)


def test_an_asset_is_saved_and_loaded_unchanged():
    asset = _asset("ast_1")
    records.save_assets([asset])
    assert records.load_assets() == {"ast_1": asset}


def test_an_edited_asset_replaces_the_saved_one():
    records.save_assets([_asset("ast_1")])
    records.save_assets([_asset("ast_1", text="new", edited=True)])
    loaded = records.load_assets()["ast_1"]
    assert (loaded.text, loaded.edited, len(records.load_assets())) == ("new", True, 1)


def test_a_kit_is_saved_completely_or_not_at_all():
    broken = _asset("ast_2").model_copy(update={"brief": None})  # NOT NULL: the database refuses this row
    with pytest.raises(DatabaseError):
        records.save_assets([_asset("ast_1"), broken])
    assert records.load_assets() == {}


def test_assets_are_deleted_and_unknown_ids_are_ignored():
    records.save_assets([_asset("ast_1"), _asset("ast_2")])
    records.delete_assets(["ast_1", "ast_unknown"])
    records.delete_assets([])
    assert list(records.load_assets()) == ["ast_2"]


def test_a_conversation_is_saved_with_its_turns_and_loaded_unchanged():
    conversation = _conversation("cnv_1")
    records.save_conversation(conversation)
    conversation.turns.append(conversation.turns[0].model_copy(update={"question": "second"}))
    records.save_conversation(conversation)  # a new turn: the saved chat is replaced
    assert records.load_conversations() == {"cnv_1": conversation}
    records.delete_conversations(["cnv_1"])
    assert records.load_conversations() == {}


def test_the_import_of_assets_and_chats_skips_known_ids_and_unknown_projects(tmp_path):
    generated, chats = tmp_path / "generated", tmp_path / "conversations"
    for folder, record in [(generated, _asset("ast_1")), (generated, _asset("ast_2", project_id="prj_gone")),
                           (chats, _conversation("cnv_1"))]:
        (folder / record.project_id).mkdir(parents=True, exist_ok=True)
        (folder / record.project_id / f"{record.id}.json").write_text(record.model_dump_json(), encoding="utf-8")

    assert (import_files.import_assets(generated), import_files.import_conversations(chats)) == (1, 1)
    assert (import_files.import_assets(generated), import_files.import_conversations(chats)) == (0, 0)
    assert list(records.load_assets()) == ["ast_1"] and list(records.load_conversations()) == ["cnv_1"]
    assert records.load_assets()["ast_1"] == _asset("ast_1").model_copy(
        update={"created_at": records.load_assets()["ast_1"].created_at})


def test_an_asset_needs_an_existing_project():
    with pytest.raises(DatabaseError):
        records.save_assets([_asset("ast_1", project_id="prj_unknown")])


# ---------- Usage log ----------

def _call(cost: float, when: datetime, user_id: str | None = OWNER.id, operation: str = "ask/answer",
          project_id: str | None = db.DEFAULT_PROJECT_ID) -> UsageRecord:
    return UsageRecord(timestamp=when, operation=operation, kind="chat", model="m", input_tokens=10, output_tokens=5,
                       input_cost=cost, output_cost=0.0, cost=cost, cost_source="estimate", project_id=project_id,
                       user_id=user_id)


NOON = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
TODAY, MONTH = NOON.replace(hour=0), NOON.replace(day=1, hour=0)


def test_spending_sums_today_this_month_and_the_whole_app():
    for rec in [_call(1.0, NOON), _call(2.0, NOON.replace(day=2)),  # the user: today, earlier this month
                _call(4.0, NOON.replace(month=10)),  # last month: not counted
                _call(8.0, NOON, user_id=STRANGER.id, project_id="prj_other"),  # someone else today
                _call(16.0, NOON, user_id=None)]:  # before sign-in existed, in the user's project
        records.add_usage(rec)
    user_today, user_month, app_today = records.spending(OWNER.id, [db.DEFAULT_PROJECT_ID], TODAY, MONTH)
    assert (user_today, user_month, app_today) == (17.0, 19.0, 25.0)
    assert records.spending(STRANGER.id, ["prj_other"], TODAY, MONTH) == (8.0, 8.0, 25.0)


def test_times_from_other_time_zones_count_in_utc():
    berlin = timezone(timedelta(hours=1))
    records.add_usage(_call(1.0, datetime(2026, 11, 6, 0, 30, tzinfo=berlin)))  # = 23:30 UTC the day before
    assert records.spending(OWNER.id, [], TODAY, MONTH) == (0.0, 1.0, 0.0)
    assert records.recent_usage(1)[0].timestamp == datetime(2026, 11, 5, 23, 30, tzinfo=timezone.utc)


def test_the_report_sums_per_operation_and_lists_the_latest_calls():
    records.add_usage(_call(1.0, NOON, operation="ask/answer"))
    records.add_usage(_call(3.0, NOON.replace(hour=13), operation="generate/generate"))
    records.add_usage(_call(2.0, NOON.replace(hour=14), operation="ask/answer", user_id=STRANGER.id))
    report = usage.report(10, OWNER.id, [db.DEFAULT_PROJECT_ID])
    assert (report.totals.calls, report.totals.cost, report.totals.input_tokens) == (2, 4.0, 20)
    assert list(report.by_operation) == ["generate/generate", "ask/answer"]  # highest cost first
    assert [r.cost for r in report.recent] == [3.0, 1.0]  # newest first, only the user's
    assert usage.report(1).recent[0].user_id == STRANGER.id  # all users, the latest one


def test_a_call_is_logged_even_if_saving_it_fails(monkeypatch):
    def broken(rec):
        raise DatabaseError("Database error (OperationalError)")
    monkeypatch.setattr(records, "add_usage", broken)
    monkeypatch.setattr(usage, "_totals", UsageTotals())
    usage.record(_call(1.0, NOON))  # no exception: the model call's request goes on
    assert usage._totals.calls == 1


def test_the_import_of_the_usage_log_skips_known_calls_and_bad_lines(tmp_path):
    path = tmp_path / "usage.jsonl"
    path.write_text("\n".join([_call(1.0, NOON).model_dump_json(), "not json",
                               _call(2.0, NOON.replace(hour=13)).model_dump_json()]), encoding="utf-8")
    assert import_files.import_usage(path) == 2
    assert import_files.import_usage(path) == 0
    assert records.usage_totals().cost == 3.0
