"""In-memory stores of the app, keyed by id (formerly dummy_data.py; imported as `db`).

The module-level dicts (projects, sources, chunks, summaries, assets) are the working copy the API
reads from. Sources, chunks, summaries and assets are persisted on disk by storage.py and loaded into these dicts on
startup; projects are not persisted yet, so only the fixed demo project exists.
"""

from datetime import datetime, timezone
from uuid import uuid4

from app.core.schemas import Asset, BookSummary, Chunk, Project, Source

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


# Projects by id; starts with one demo project.
projects: dict[str, Project] = {
    DEFAULT_PROJECT_ID: Project(
        id=DEFAULT_PROJECT_ID,
        name="Demo campaign",
        description="Dummy project for UI development",
        created_at=now(),
    )
}

# Sources and their chunks by id; filled from disk on startup (ingestion.restore_sources) and by uploads.
sources: dict[str, Source] = {}
chunks: dict[str, Chunk] = {}

# Book summaries by source id; filled from disk on startup (ingestion.restore_sources) and by summary.py.
summaries: dict[str, BookSummary] = {}

# Generated assets by id; filled from disk on startup (storage.load_assets) and by generation.
assets: dict[str, Asset] = {}
