"""Tests of the database layer (app/db) on the in-memory test database of conftest.py: projects, assets and chats
saved and loaded, one project per owner, a kit saved in one transaction, books and their chunks, the usage log and the
connection settings."""

from datetime import datetime, timedelta, timezone

import pytest

from app.core import config, usage
from app.core import state as db
from app.core.schemas import (Asset, BookSummary, ChapterSummary, ChatTurn, Chunk, ChunkLocation, Citation,
                              Conversation, DiscussionAnalysis, Project, SearchHit, Source, UsageRecord, UsageTotals)
from app.db import database, records
from app.db.database import DatabaseError
from app.db.tables import AssetRow, ConversationRow, DiscussionRow, SourceRow, SummaryRow
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
    assert set(DiscussionRow.__table__.columns.keys()) == set(DiscussionAnalysis.model_fields)


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


# ---------- Sources (books) and summaries ----------

def _source(source_id: str, sha256: str = "", **changes) -> Source:
    source = Source(id=source_id, project_id=db.DEFAULT_PROJECT_ID, filename=f"{source_id}.pdf", kind="document",
                    size_bytes=1234, status="ready", progress=100, chunk_count=7, created_at=db.now(),
                    author="J. J. Butler", sha256=sha256)
    return source.model_copy(update=changes)


def _summary(source_id: str, text: str = "About money.") -> BookSummary:
    return BookSummary(source_id=source_id, summary=text, themes=["speculation", "risk"],
                       chapters=[ChapterSummary(chapter="I", first_page=1, last_page=9, summary="Starts.")],
                       model="m", prompt_version="summary@1", tokens=99, created_at=db.now())


def test_every_source_and_summary_field_has_a_column():
    assert set(SourceRow.__table__.columns.keys()) == set(Source.model_fields)
    assert set(SummaryRow.__table__.columns.keys()) == set(BookSummary.model_fields)


def test_a_source_is_saved_updated_and_loaded():
    records.add_source(_source("src_a", "abc"))
    assert records.update_source(_source("src_a", "abc", status="failed", error="Retry")) is True
    loaded = records.load_sources()["src_a"]
    assert (loaded.status, loaded.error, loaded.author) == ("failed", "Retry", "J. J. Butler")


def test_an_update_of_a_deleted_source_writes_nothing():
    """A running ingestion must not bring a deleted book back."""
    assert records.update_source(_source("src_gone")) is False
    assert records.load_sources() == {}


def test_the_same_file_only_once_per_project():
    records.add_source(_source("src_a", "abc"))
    with pytest.raises(DatabaseError):
        records.add_source(_source("src_b", "abc"))
    records.add_source(_source("src_c", ""))  # older books without a checksum are not compared
    records.add_source(_source("src_d", ""))
    assert set(records.load_sources()) == {"src_a", "src_c", "src_d"}


def test_a_summary_is_saved_replaced_and_deleted_with_its_book():
    records.add_source(_source("src_a"))
    records.save_summary(_summary("src_a"))
    records.save_summary(_summary("src_a", "Regenerated."))
    assert records.load_summaries() == {"src_a": _summary("src_a", "Regenerated.").model_copy(
        update={"created_at": records.load_summaries()["src_a"].created_at})}
    records.save_assets([_asset("ast_1")])
    records.save_conversation(_conversation("cnv_1"))
    records.delete_source("src_a", ["ast_1"], ["cnv_1"])
    assert (records.load_sources(), records.load_summaries(), records.load_assets(),
            records.load_conversations()) == ({}, {}, {}, {})


def test_a_summary_needs_its_book():
    with pytest.raises(DatabaseError):
        records.save_summary(_summary("src_unknown"))


# ---------- Chunks and their vectors ----------

def _chunks(source_id: str, n: int) -> list[Chunk]:
    return [Chunk(id=f"chk_{source_id}_{i}", source_id=source_id, text=f"Text {i}.", token_count=3,
                  location=ChunkLocation(chapter="I", page=i)) for i in range(1, n + 1)]


def test_chunks_are_replaced_in_reading_order_with_their_vectors():
    records.add_source(_source("src_a"))
    records.replace_chunks(db.DEFAULT_PROJECT_ID, "src_a", _chunks("src_a", 3), ["h\n\nText"] * 3,
                           [[1.0, 0.0], [0.0, 1.0], [0.6, 0.8]], "model--v2")
    records.replace_chunks(db.DEFAULT_PROJECT_ID, "src_a", _chunks("src_a", 2), ["h\n\nText"] * 2,
                           [[1.0, 0.0], [0.0, 1.0]], "model--v2")  # re-indexed: fewer chunks
    loaded = records.load_chunks()["src_a"]
    assert [c.id for c in loaded] == ["chk_src_a_1", "chk_src_a_2"] and loaded[1].location.page == 2
    assert records.chunk_counts("model--v2") == {"src_a": 2} and records.chunk_counts("other--v2") == {}
    assert records.chunk_embeddings(["chk_src_a_2", "chk_unknown"]) == {"chk_src_a_2": [0.0, 1.0]}
    assert records.count_all_chunks() == 2


def test_a_deleted_book_gets_no_chunks_and_loses_its_own():
    with pytest.raises(DatabaseError):  # the book is gone (e.g. deleted while it was being embedded)
        records.replace_chunks(db.DEFAULT_PROJECT_ID, "src_gone", _chunks("src_gone", 1), ["x"], [[1.0]], "k")
    records.add_source(_source("src_a"))
    records.replace_chunks(db.DEFAULT_PROJECT_ID, "src_a", _chunks("src_a", 2), ["x", "y"], [[1.0], [0.5]], "k")
    records.delete_source("src_a")
    assert records.load_chunks() == {}
