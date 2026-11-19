"""Where the agents' paused runs are kept: one LangGraph checkpointer for the Page inbox, the engagement and the book
post agents (page_inbox.py, engagement.py, book_post.py).

    DATABASE_URL is PostgreSQL   PostgresSaver: the runs are in the database (schema "private"), so a proposal that
                                 waits in Telegram survives a server restart or a redeploy, and the author's answer
                                 still finds it
    otherwise (tests)            MemorySaver: in this process only

The tables (checkpoints, checkpoint_blobs, checkpoint_writes, checkpoint_migrations) belong to LangGraph: setup()
creates and migrates them on first use, not Alembic. They are in "private", which Supabase's REST API does not serve
(see db/tables.py), and have row-level security on without a policy, like the app's tables; the server reaches them
as the database owner.

Each agent restores itself from here on startup (restore() in each agent): runs still waiting become its current
proposal again, finished runs tell it what was already decided, and runs finished more than KEEP_DAYS ago are deleted.
"""

import logging
from datetime import UTC, datetime, timedelta
from functools import cache

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

from app.core import config

logger = logging.getLogger(__name__)

SCHEMA = "private"
KEEP_DAYS = 30  # finished runs are kept this long (what was decided), then deleted
POOL_SIZE = 3
TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations")


def _postgres_url() -> str:
    """DATABASE_URL as psycopg takes it ("" when it is not PostgreSQL)."""
    url = config.DATABASE_URL
    return "postgresql://" + url[len("postgresql+psycopg://"):] if url.startswith("postgresql+psycopg://") else ""


@cache
def checkpointer() -> BaseCheckpointSaver:
    """The shared checkpointer (created on first use; the PostgreSQL tables are set up then)."""
    url = _postgres_url()
    if not url:
        return MemorySaver()
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    def configure(conn) -> None:  # every connection works in "private" (autocommit: the setting stays)
        conn.execute(f"SET search_path TO {SCHEMA}")

    # prepare_threshold=None: no prepared statements, which Supabase's pooler (Supavisor) does not keep
    pool = ConnectionPool(url, min_size=1, max_size=POOL_SIZE, configure=configure, open=True,
                          kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row})
    saver = PostgresSaver(pool)
    saver.setup()
    with saver._cursor() as cur:  # noqa: SLF001 (like every app table: row-level security on, no policy)
        for table in TABLES:
            cur.execute(f"ALTER TABLE {SCHEMA}.{table} ENABLE ROW LEVEL SECURITY")
    logger.info("Agent runs are kept in the database (%s.checkpoints)", SCHEMA)
    return saver


def thread_ids(prefix: str = "") -> list[str]:
    """The ids of all runs kept (whose id starts with `prefix`)."""
    saver = checkpointer()
    if isinstance(saver, MemorySaver):
        ids = list(saver.storage)
    else:
        with saver._cursor() as cur:  # noqa: SLF001 (no public way to list threads without their checkpoints)
            cur.execute("SELECT DISTINCT thread_id FROM checkpoints WHERE checkpoint_ns = ''")
            ids = [row["thread_id"] for row in cur.fetchall()]
    return [i for i in ids if i.startswith(prefix)]


def is_old(created_at: str | None) -> bool:
    """True if a run's last step (a checkpoint's created_at, ISO time) is more than KEEP_DAYS ago."""
    if not created_at:
        return False
    moment = datetime.fromisoformat(created_at)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return datetime.now(UTC) - moment > timedelta(days=KEEP_DAYS)


def delete(thread_id: str) -> None:
    """Forget a finished run."""
    checkpointer().delete_thread(thread_id)
