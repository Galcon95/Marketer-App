"""In-memory working copy of the app's data, keyed by id (imported as `db`).

The module-level dicts (projects, sources, chunks, summaries, assets, conversations) are what the API reads from.
Everything is saved in the database (Supabase PostgreSQL, app/db/records.py) and loaded into these dicts on startup;
every change is written to the database as well. The book files and covers are in Supabase Storage (core/files.py).
Discussion analyses and the usage log are read from the database directly (records.py), not kept here.
"""

from datetime import datetime, timezone
from uuid import uuid4

from app.core.schemas import Asset, BookSummary, Chunk, Conversation, Project, Source

DEFAULT_PROJECT_ID = "demo-campaign"


def now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime, used for all created_at fields."""
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    """Create a short, unique, readable id such as "src_1a2b3c4d".

    Joins the prefix with the first 8 hex characters of a random UUID4.

    Args:
        prefix: Type marker for the id, e.g. "prj", "src", "ast".

    Returns:
        The new id string.
    """
    return f"{prefix}_{uuid4().hex[:8]}"


# Projects by id. A project is a client (shown as "Current client" in the GUI): its books, chats, campaigns and
# assets. Each signed-in user owns one (accounts.py). The default project holds the data from before sign-in
# existed (the id "demo-campaign" stays because its data in the database and in Storage is stored under it); it has no owner
# until DEFAULT_CLIENT_OWNER signs in. The saved projects (records.load_projects) replace these on startup.
projects: dict[str, Project] = {
    DEFAULT_PROJECT_ID: Project(
        id=DEFAULT_PROJECT_ID,
        name="Peter Schmidt",
        description="The default client: all books, chats, campaigns and assets",
        created_at=now(),
    )
}

# Sources and their chunks by id; filled from the database on startup (ingestion.restore_sources) and by uploads.
sources: dict[str, Source] = {}
chunks: dict[str, Chunk] = {}

# Book summaries by source id; filled from the database on startup (ingestion.restore_sources) and by summary.py.
summaries: dict[str, BookSummary] = {}

# Generated assets by id; filled from the database on startup (records.load_assets) and by generation.
assets: dict[str, Asset] = {}

# "Ask your book" conversations by id; filled from the database on startup (records.load_conversations) and by
# /ask.
conversations: dict[str, Conversation] = {}
