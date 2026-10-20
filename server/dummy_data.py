"""In-memory dummy data. Replaced step by step by real storage, ingestion and RAG.

The module-level dicts (projects, sources, chunks, assets) act as a fake database keyed by id.
They live only in the server process and are reset to the demo content on every restart.
"""

from datetime import datetime, timezone
from uuid import uuid4

from schemas import Asset, Chunk, ChunkLocation, Citation, Project, Source

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

# Sources by id; two demo sources (a book and a video) that have no files on disk.
sources: dict[str, Source] = {
    "src_demo0001": Source(
        id="src_demo0001",
        project_id=DEFAULT_PROJECT_ID,
        filename="sample_manuscript.pdf",
        kind="document",
        size_bytes=2_400_000,
        status="ready",
        progress=100,
        chunk_count=3,
        created_at=now(),
    ),
    "src_demo0002": Source(
        id="src_demo0002",
        project_id=DEFAULT_PROJECT_ID,
        filename="author_interview.mp4",
        kind="video",
        size_bytes=48_000_000,
        status="ready",
        progress=100,
        chunk_count=2,
        created_at=now(),
    ),
}

# Chunks by id; fake ingestion output of the two demo sources.
chunks: dict[str, Chunk] = {
    c.id: c
    for c in [
        Chunk(id="chk_0001", source_id="src_demo0001", token_count=48,
              location=ChunkLocation(chapter="ch_01", page=9),
              text="Dummy chunk: the opening scene introduces the main character and the central problem of the story."),
        Chunk(id="chk_0002", source_id="src_demo0001", token_count=52,
              location=ChunkLocation(chapter="ch_04", page=112),
              text="Dummy chunk: a memorable, quotable line that captures the hook of the book in one sentence."),
        Chunk(id="chk_0003", source_id="src_demo0001", token_count=45,
              location=ChunkLocation(chapter="ch_09", page=241),
              text="Dummy chunk: the stakes rise as the character realises what failure would cost."),
        Chunk(id="chk_0004", source_id="src_demo0002", token_count=60,
              location=ChunkLocation(start_time="00:02:15", end_time="00:03:02"),
              text="Dummy transcript: the author explains why they wrote the book and who it is for."),
        Chunk(id="chk_0005", source_id="src_demo0002", token_count=57,
              location=ChunkLocation(start_time="00:12:34", end_time="00:13:20"),
              text="Dummy transcript: the author talks about the research behind the story."),
    ]
}

# Generated assets by id; empty until the user generates something.
assets: dict[str, Asset] = {}


def dummy_citation(chunk: Chunk, score: float) -> Citation:
    """Build a Citation pointing at a chunk, quoting its first 80 characters.

    Args:
        chunk: The chunk to cite.
        score: Similarity score to attach to the citation.

    Returns:
        A Citation with the chunk's id, source and location.
    """
    return Citation(chunk_id=chunk.id, source_id=chunk.source_id, location=chunk.location,
                    quote=chunk.text[:80], score=score)
