"""Shared helpers of the API routers: 404 lookups and vector search with HTTP errors."""

from fastapi import HTTPException

from app.core import state as db
from app.core.schemas import Chunk, Project, Source
from app.rag import vectorstore
from app.rag.retrieval import retrieve_chunks


def get_project_or_404(project_id: str) -> Project:
    """Look up a project by id, or abort the request with 404 if it does not exist.

    Args:
        project_id: Id of the project to find.

    Returns:
        The stored Project (without computed counts).

    Raises:
        HTTPException: 404 when no project has this id.
    """
    project = db.projects.get(project_id)
    if project is None:
        raise HTTPException(404, f"Project '{project_id}' not found")
    return project


def get_source_or_404(source_id: str) -> Source:
    """Look up a source by id, or abort the request with 404 if it does not exist.

    Args:
        source_id: Id of the source to find.

    Returns:
        The stored Source.

    Raises:
        HTTPException: 404 when no source has this id.
    """
    source = db.sources.get(source_id)
    if source is None:
        raise HTTPException(404, f"Source '{source_id}' not found")
    return source


def retrieve(project_id: str, query: str, k: int, source_ids: list[str] | None = None,
             operation: str = "search") -> list[tuple[Chunk, float]]:
    """Find the project's chunks most similar to a query (vector search in Chroma).

    Wraps retrieval.retrieve_chunks and turns vector store errors into HTTP errors.

    Args:
        project_id: Project to search in.
        query: Natural-language query.
        k: Maximum number of results.
        source_ids: Optional filter: only search these sources.
        operation: What the search is for, for the usage log (e.g. "search", "verify").

    Returns:
        (chunk, similarity) pairs, best first.

    Raises:
        HTTPException: 503 if no embedding API key is configured, 502 if the search fails.
    """
    try:
        return retrieve_chunks(project_id, query, k, source_ids, operation=operation)
    except vectorstore.VectorStoreError as e:
        raise HTTPException(503 if not vectorstore.is_configured() else 502, str(e)) from e
