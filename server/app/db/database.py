"""Connection to the database: one SQLAlchemy engine for the whole server, created on first use from DATABASE_URL.

Use `with database.session() as s:` for every read or write: it commits at the end of the block, rolls back if
the block fails, and turns any SQLAlchemy error into DatabaseError.

Supabase: use the "Session pooler" connection string (Connect → Session pooler; port 5432). It works over IPv4,
unlike the direct connection on the free plan, and keeps a connection per server worker like a normal Postgres.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import DATABASE_URL

_engine: Engine | None = None
_sessions: sessionmaker[Session] | None = None


class DatabaseError(OSError):
    """Reading or writing the database failed (or DATABASE_URL is not set). An OSError, like a failed file write,
    so the callers that answered "could not be saved" (500) for a file do the same for the database."""


def engine() -> Engine:
    """The engine, created on first use.

    Raises:
        DatabaseError: If DATABASE_URL is not set.
    """
    global _engine, _sessions
    if _engine is None:
        if not DATABASE_URL:
            raise DatabaseError("DATABASE_URL is not set (server/.env); the server needs the database.")
        # pre_ping: a connection the pooler closed while idle is replaced instead of failing the next request.
        use_engine(create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=5))
    return _engine


def use_engine(new_engine: Engine) -> None:
    """Use this engine from now on (on first use, and in tests: an in-memory SQLite database)."""
    global _engine, _sessions
    _engine = new_engine
    _sessions = sessionmaker(new_engine, expire_on_commit=False)


@contextmanager
def session() -> Iterator[Session]:
    """A session in one transaction: committed when the block ends, rolled back if it raises.

    Raises:
        DatabaseError: If the database cannot be reached or a statement fails.
    """
    engine()
    try:
        with _sessions() as s, s.begin():
            yield s
    except SQLAlchemyError as e:
        # The details (statement, parameters) stay in the chained exception for the log, not in the message.
        raise DatabaseError(f"Database error ({type(e).__name__})") from e
