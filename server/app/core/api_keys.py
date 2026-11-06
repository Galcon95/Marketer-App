"""Personal API keys: how external MCP clients (Claude Desktop via mcp-remote) prove which user they act for.

A key looks like "mk_" + 43 random characters (32 random bytes). It is shown to its user once, when it is created;
the server keeps only its SHA-256 hash, so a leaked table does not reveal any key. (A slow password hash
like bcrypt is not needed: the key is random and long, not a password a person chose.) A user can have up to
max_api_keys keys (limits.toml), e.g. one per tool, and revokes a key by deleting it.

Keys are saved in the database table private.api_keys (app/db), which Supabase's REST API cannot read; this
module keeps a copy in memory, loaded on startup, so checking a key needs no database query.
"""

import hashlib
import hmac
import logging
import secrets
import threading
from datetime import timedelta

from app.core import state as db
from app.core.auth import User
from app.core.limits import LIMITS
from app.core.schemas import ApiKey
from app.db import records

logger = logging.getLogger(__name__)

PREFIX = "mk_"
SHOWN_CHARS = 8  # characters after the prefix kept for display ("mk_AbC123x7…"), so a user can tell keys apart
LAST_USED_PRECISION = timedelta(minutes=5)  # last_used_at is saved at most this often per key (not on every call)

_keys: dict[str, ApiKey] = {}  # by key id
_lock = threading.Lock()


class TooManyKeys(Exception):
    """The user already has max_api_keys keys."""


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def load() -> None:
    """Read the saved keys from the database (called once on server startup).

    Raises:
        DatabaseError: If the database cannot be read (the server then does not start: no key would work).
    """
    keys = records.load_api_keys()
    _keys.clear()
    _keys.update({k.id: k for k in keys})


def create(user: User, name: str) -> tuple[ApiKey, str]:
    """Create a new key for the user.

    Args:
        user: The signed-in user who will own the key.
        name: What the key is for, e.g. "Claude Desktop" (shown in the key list).

    Returns:
        The saved key record and the key itself. The key is not stored anywhere: show it to the user once.

    Raises:
        TooManyKeys: If the user already has max_api_keys keys.
        DatabaseError: If the key cannot be saved (it is then not created).
    """
    key = PREFIX + secrets.token_urlsafe(32)
    record = ApiKey(id=db.new_id("key"), user_id=user.id, email=user.email, name=name.strip(),
                    shown=key[:len(PREFIX) + SHOWN_CHARS], key_hash=_hash(key), created_at=db.now())
    with _lock:
        if len(keys_of(user)) >= LIMITS.per_user.max_api_keys:
            raise TooManyKeys(f"You can have at most {LIMITS.per_user.max_api_keys} keys. Revoke one first.")
        records.add_api_key(record)  # first in the database: if that fails, the key does not exist anywhere
        _keys[record.id] = record
    logger.info("Created API key %s", record.id)
    return record, key


def keys_of(user: User) -> list[ApiKey]:
    """The user's keys, oldest first."""
    return sorted((k for k in _keys.values() if k.user_id == user.id), key=lambda k: k.created_at)


def revoke(user: User, key_id: str) -> bool:
    """Delete one of the user's keys; it stops working at once.

    Returns:
        True if it was deleted; False if the user has no key with this id (another user's key counts as unknown).

    Raises:
        DatabaseError: If the change cannot be saved (the key then still works).
    """
    with _lock:
        record = _keys.get(key_id)
        if record is None or record.user_id != user.id:
            return False
        records.delete_api_key(key_id)  # first in the database: if that fails, the key still works everywhere
        del _keys[key_id]
    logger.info("Revoked API key %s", key_id)
    return True


def user_for(key: str) -> User | None:
    """The user a key belongs to, or None for a wrong, malformed or revoked key. Notes when the key was last used.

    Args:
        key: The key as the client sent it.
    """
    if not key.startswith(PREFIX):
        return None
    digest = _hash(key)
    record = next((k for k in list(_keys.values()) if hmac.compare_digest(k.key_hash, digest)), None)
    if record is None:
        return None
    now = db.now()
    if record.last_used_at is None or now - record.last_used_at >= LAST_USED_PRECISION:
        with _lock:
            if record.id in _keys:  # not revoked meanwhile
                _keys[record.id] = record.model_copy(update={"last_used_at": now})
                try:
                    records.set_api_key_last_used(record.id, now)
                except OSError as e:  # DatabaseError; only the "last used" date is lost
                    logger.warning("Could not save the last use of API key %s: %s", record.id, e)
    return User(id=record.user_id, email=record.email)
