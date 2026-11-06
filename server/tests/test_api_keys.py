"""Tests of the personal API keys (api_keys.py): creating, finding the user of a key, revoking, saving in the
database (the in-memory test database of conftest.py), and that the key itself is never stored."""

from datetime import timedelta

import pytest
from sqlalchemy import text

from app.core import api_keys
from app.db import records
from app.db.database import DatabaseError
from app.core.limits import AppWide, Limits, PerUser
from tests.conftest import OWNER, STRANGER


def test_a_new_key_finds_its_user():
    record, key = api_keys.create(OWNER, "  Claude Desktop ")
    assert key.startswith("mk_") and len(key) == 3 + 43
    assert (record.name, record.user_id, record.shown) == ("Claude Desktop", OWNER.id, key[:11])
    assert api_keys.user_for(key) == OWNER


def test_every_key_is_different():
    keys = {api_keys.create(OWNER, f"k{i}")[1] for i in range(5)}
    assert len(keys) == 5


@pytest.mark.parametrize("wrong", ["", "mk_", "mk_wrong", "Bearer mk_x", "sk-abc"])
def test_wrong_keys_find_nobody(wrong):
    api_keys.create(OWNER, "k")
    assert api_keys.user_for(wrong) is None


def test_a_key_that_differs_by_one_character_finds_nobody():
    _, key = api_keys.create(OWNER, "k")
    assert api_keys.user_for(key[:-1] + ("A" if key[-1] != "A" else "B")) is None


def test_the_key_itself_is_never_saved(test_database):
    _, key = api_keys.create(OWNER, "k")
    with test_database.connect() as connection:
        rows = [tuple(row) for row in connection.execute(text("SELECT * FROM api_keys"))]
    saved = repr(rows)
    assert key not in saved and key[11:] not in saved  # only the shown beginning and the hash
    assert [k.key_hash for k in records.load_api_keys()] == [api_keys._hash(key)]


def test_keys_are_loaded_again_after_a_restart():
    _, key = api_keys.create(OWNER, "k")
    api_keys._keys.clear()
    assert api_keys.user_for(key) is None
    api_keys.load()
    assert api_keys.user_for(key) == OWNER


def test_an_unreachable_database_stops_the_start(monkeypatch):
    """No silent start without keys: load() raises, so the server does not start (server.restore_data)."""
    def broken():
        raise DatabaseError("Database error (OperationalError)")
    monkeypatch.setattr(records, "load_api_keys", broken)
    with pytest.raises(DatabaseError):
        api_keys.load()


def test_a_revoked_key_stops_working_also_after_a_restart():
    record, key = api_keys.create(OWNER, "k")
    assert api_keys.revoke(OWNER, record.id) is True
    assert api_keys.user_for(key) is None
    api_keys.load()
    assert api_keys.user_for(key) is None


def test_nobody_can_revoke_another_users_key():
    record, key = api_keys.create(OWNER, "k")
    assert api_keys.revoke(STRANGER, record.id) is False
    assert api_keys.revoke(STRANGER, "key_unknown") is False
    assert api_keys.user_for(key) == OWNER


def test_each_user_sees_only_their_own_keys():
    api_keys.create(OWNER, "a")
    api_keys.create(STRANGER, "b")
    api_keys.create(OWNER, "c")
    assert [k.name for k in api_keys.keys_of(OWNER)] == ["a", "c"]
    assert [k.name for k in api_keys.keys_of(STRANGER)] == ["b"]


def test_the_number_of_keys_is_limited(monkeypatch):
    monkeypatch.setattr(api_keys, "LIMITS", Limits(per_user=PerUser(max_api_keys=2), app=AppWide()))
    api_keys.create(OWNER, "a")
    api_keys.create(OWNER, "b")
    with pytest.raises(api_keys.TooManyKeys):
        api_keys.create(OWNER, "c")
    api_keys.create(STRANGER, "a")  # counted per user


def test_a_key_is_not_created_when_it_cannot_be_saved(monkeypatch):
    def broken(record):
        raise DatabaseError("Database error (OperationalError)")
    monkeypatch.setattr(records, "add_api_key", broken)
    with pytest.raises(DatabaseError):
        api_keys.create(OWNER, "k")
    assert api_keys.keys_of(OWNER) == []


def test_a_key_still_works_when_revoking_cannot_be_saved(monkeypatch):
    record, key = api_keys.create(OWNER, "k")
    def broken(key_id):
        raise DatabaseError("Database error (OperationalError)")
    monkeypatch.setattr(records, "delete_api_key", broken)
    with pytest.raises(DatabaseError):
        api_keys.revoke(OWNER, record.id)
    assert api_keys.user_for(key) == OWNER  # memory and database still agree


def test_a_failed_save_answers_500(app, monkeypatch):
    def broken(record):
        raise DatabaseError("Database error (OperationalError)")
    monkeypatch.setattr(records, "add_api_key", broken)
    assert client_for(app, OWNER).post("/api-keys", json={"name": "k"}).status_code == 500


def test_last_use_is_noted_but_not_on_every_call(monkeypatch):
    record, key = api_keys.create(OWNER, "k")
    assert record.last_used_at is None
    api_keys.user_for(key)
    first = api_keys.keys_of(OWNER)[0].last_used_at
    assert first is not None
    api_keys.user_for(key)
    assert api_keys.keys_of(OWNER)[0].last_used_at == first  # within LAST_USED_PRECISION: not saved again
    later = first + api_keys.LAST_USED_PRECISION + timedelta(seconds=1)
    monkeypatch.setattr(api_keys.db, "now", lambda: later)
    api_keys.user_for(key)
    assert api_keys.keys_of(OWNER)[0].last_used_at == later
    assert records.load_api_keys()[0].last_used_at == later  # also in the database


# ---------- Endpoints: GET/POST /api-keys, DELETE /api-keys/{id} ----------

@pytest.fixture
def app():
    from fastapi import FastAPI
    from app.api import keys
    app = FastAPI()
    app.include_router(keys.router)
    return app


def client_for(app, user):
    from fastapi.testclient import TestClient
    from tests.conftest import sign_in
    sign_in(app, user)
    return TestClient(app)


def test_create_list_and_revoke_through_the_api(app):
    owner = client_for(app, OWNER)
    created = owner.post("/api-keys", json={"name": "Claude Desktop"})
    assert created.status_code == 201
    body = created.json()
    assert body["key"].startswith("mk_") and api_keys.user_for(body["key"]) == OWNER
    listed = owner.get("/api-keys").json()
    assert [k["id"] for k in listed] == [body["id"]]
    assert "key" not in listed[0] and "key_hash" not in listed[0]  # never again, not even the hash
    assert owner.delete(f"/api-keys/{body['id']}").status_code == 204
    assert owner.get("/api-keys").json() == []
    assert api_keys.user_for(body["key"]) is None


@pytest.mark.parametrize("name", ["", "   ", "x" * 51])
def test_a_key_needs_a_short_name(app, name):
    assert client_for(app, OWNER).post("/api-keys", json={"name": name}).status_code == 422


def test_another_users_keys_are_invisible_and_cannot_be_revoked(app):
    record, key = api_keys.create(OWNER, "mine")
    stranger = client_for(app, STRANGER)
    assert stranger.get("/api-keys").json() == []
    assert stranger.delete(f"/api-keys/{record.id}").status_code == 404
    assert api_keys.user_for(key) == OWNER


def test_too_many_keys_answers_409(app, monkeypatch):
    monkeypatch.setattr(api_keys, "LIMITS", Limits(per_user=PerUser(max_api_keys=1), app=AppWide()))
    owner = client_for(app, OWNER)
    assert owner.post("/api-keys", json={"name": "a"}).status_code == 201
    response = owner.post("/api-keys", json={"name": "b"})
    assert response.status_code == 409 and "at most 1 keys" in response.json()["detail"]


def test_the_key_endpoints_need_sign_in_and_an_api_key_is_no_sign_in(monkeypatch):
    """Mounted like in server.py (behind auth.current_user, no test sign-in): no token and an API key both get 401,
    so a leaked API key cannot create or revoke keys."""
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
    from app.api import keys
    from app.core import auth
    monkeypatch.setattr(auth, "SUPABASE_URL", "https://example.supabase.co")
    app = FastAPI()
    app.include_router(keys.router, dependencies=[Depends(auth.current_user)])
    _, key = api_keys.create(OWNER, "k")
    client = TestClient(app)
    assert client.get("/api-keys").status_code == 401
    assert client.post("/api-keys", json={"name": "x"}, headers={"Authorization": f"Bearer {key}"}).status_code == 401
    assert len(api_keys.keys_of(OWNER)) == 1
