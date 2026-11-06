"""In-memory stores of the app, keyed by id (formerly dummy_data.py; imported as `db`).

The module-level dicts (projects, sources, chunks, summaries, assets, conversations) are the working copy
the API reads from. Sources, chunks, summaries, assets and conversations are persisted on disk by storage.py and loaded into these dicts on
startup; projects are saved in the database (app/db/records.py, loaded on startup).
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
# existed (the id "demo-campaign" stays because data on disk and in Chroma is stored under it); it has no owner
# until DEFAULT_CLIENT_OWNER signs in. The saved projects (records.load_projects) replace these on startup.
projects: dict[str, Project] = {
    DEFAULT_PROJECT_ID: Project(
        id=DEFAULT_PROJECT_ID,
        name="Peter Schmidt",
        description="The default client: all books, chats, campaigns and assets",
        created_at=now(),
    )
}

# Sources and their chunks by id; filled on startup (ingestion.restore_sources: sources from the database, chunks
# from disk) and by uploads.
sources: dict[str, Source] = {}
chunks: dict[str, Chunk] = {}

# Book summaries by source id; filled from the database on startup (ingestion.restore_sources) and by summary.py.
summaries: dict[str, BookSummary] = {}

# Generated assets by id; filled from the database on startup (records.load_assets) and by generation.
assets: dict[str, Asset] = {}

# "Ask your book" conversations by id; filled from the database on startup (records.load_conversations) and by
# /ask.
conversations: dict[str, Conversation] = {}
