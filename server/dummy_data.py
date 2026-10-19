"""In-memory dummy data. Replaced step by step by real storage, ingestion and RAG."""

from datetime import datetime, timezone
from uuid import uuid4

from schemas import Asset, Chunk, ChunkLocation, Citation, Project, Source

DEFAULT_PROJECT_ID = "demo-campaign"


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


projects: dict[str, Project] = {
    DEFAULT_PROJECT_ID: Project(
        id=DEFAULT_PROJECT_ID,
        name="Demo campaign",
        description="Dummy project for UI development",
        created_at=now(),
    )
}

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

assets: dict[str, Asset] = {}


def dummy_citation(chunk: Chunk, score: float) -> Citation:
    return Citation(chunk_id=chunk.id, source_id=chunk.source_id, location=chunk.location,
                    quote=chunk.text[:80], score=score)
