"""Vector store for RAG retrieval, built on LangChain: chunk embeddings in PostgreSQL with pgvector.

    "book · chapter" header + chunk ──OpenAIEmbeddings──► vector ──► table chunks (records.replace_chunks)
    query ──OpenAIEmbeddings──► vector ──PGVectorStore──► nearest chunks by cosine similarity (relevance 0-1)

Each chunk is embedded with a contextual header, its book and chapter ("Successful Stock Speculation — J. J.
Butler · CHAPTER XVII. SHORT SELLING"), so a passage like "He then sold the remainder at a loss" carries what it is
about in its vector, not only in the filter metadata. The prompt still shows the plain chunk text.

The chunks table (app/db/tables.py, ChunkRow) holds each chunk with its text, location, the embedded text and the
vector; all chunks of a book are replaced in one transaction, so searches see the old ones until the new ones are
complete. LangChain's PGVectorStore searches it, filtered by project, EMBEDDING_KEY, books, chapters and pages.
EMBEDDING_KEY (model and INDEX_FORMAT) is stored per chunk, because vectors of different models or differently built
texts cannot be compared: after a change, the server marks the books for Retry on startup (ingestion.restore_sources).

The search is exact: every chunk of the project is compared (pgvector without an index). With a few thousand chunks
that takes milliseconds, and unlike the approximate HNSW index Chroma used it cannot miss a true nearest chunk.
(pgvector's indexes take at most 2,000 dimensions; text-embedding-3-large has 3,072. For far more chunks: a halfvec
HNSW index.)

PGVectorStore works asynchronously. It runs on its own event loop in a background thread: a selector loop, because
psycopg cannot run asynchronously on Windows' default loop.

Provider, API key and embedding model come from core/config.py (OPENROUTER_API_KEY or
OPENAI_API_KEY, optional EMBEDDING_MODEL).
"""

import asyncio
import logging
import re
import selectors
import threading
from collections.abc import Callable
from functools import cache, lru_cache

import numpy as np
from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGEngine, PGVectorStore
from sqlalchemy.ext.asyncio import create_async_engine

from app.core import usage
from app.core.config import (API_KEY, BASE_URL, DATABASE_URL, EMBEDDING_MODEL, EMBEDDING_TIMEOUT_SECONDS,
                             LLM_MAX_RETRIES, PROVIDER)
from app.core.schemas import Chunk
from app.db import records

logger = logging.getLogger(__name__)

EMBED_BATCH = 64  # chunks per embedding request; also the step size of the progress updates
# How the embedded text is built; part of EMBEDDING_KEY, so change it whenever _content changes.
# "v2": "book · chapter" header in each chunk's text.
INDEX_FORMAT = "v2"
EMBEDDING_KEY = f"{re.sub(r'[^a-zA-Z0-9._-]', '-', EMBEDDING_MODEL.split('/')[-1])}--{INDEX_FORMAT}"
# The chunks table's columns PGVectorStore may filter on (tables.ChunkRow).
METADATA_COLUMNS = ["source_id", "project_id", "chapter", "page", "embedding_key"]


class VectorStoreError(Exception):
    """A vector store problem whose message can be shown to the user (missing key, API error, ...)."""


# ---------- Public API ----------
def is_configured() -> bool:
    """True if an API key (OpenRouter or OpenAI) is set, i.e. texts can be embedded."""
    return bool(API_KEY)


def add_chunks(project_id: str, source_id: str, chunks: list[Chunk], on_progress: Callable[[float], None] | None = None,
               title: str | None = None) -> None:
    """Embed the chunks of a source and save them with their vectors, replacing the source's previous chunks.

    The embeddings are made in batches (progress after each); then all chunks are saved in one transaction, so the
    old chunks stay searchable until the new ones are complete.

    Args:
        project_id: Project the source belongs to.
        source_id: Source the chunks belong to.
        chunks: All chunks of the source, in reading order.
        on_progress: Optional callback with the fraction of chunks embedded (0.0-1.0).
        title: Readable name of the book, embedded in each chunk's header (retrieval.source_name).

    Raises:
        VectorStoreError: If no API key is configured, embedding fails or the chunks cannot be saved (also when the
            source was deleted meanwhile).
    """
    if not is_configured():
        raise _no_key()
    contents = [_content(c, title) for c in chunks]
    embeddings: list[list[float]] = []
    try:
        for start in range(0, len(chunks), EMBED_BATCH):
            batch = chunks[start:start + EMBED_BATCH]
            embeddings += _embeddings().embed_documents(contents[start:start + EMBED_BATCH])
            usage.record_embedding("embed_chunks", EMBEDDING_MODEL, tokens=sum(c.token_count for c in batch),
                                   project_id=project_id, source_id=source_id)
            if on_progress:
                on_progress(min(start + EMBED_BATCH, len(chunks)) / len(chunks))
    except Exception as e:
        raise VectorStoreError(f"Embedding failed: {e}") from e
    try:
        records.replace_chunks(project_id, source_id, chunks, contents, embeddings, EMBEDDING_KEY)
    except OSError as e:  # DatabaseError
        raise VectorStoreError("The chunks could not be saved. Press Retry.") from e


def delete_source(project_id: str, source_id: str) -> None:
    """Remove all chunks and vectors of a source (no API key needed). Deleting the source removes them too."""
    records.delete_chunks(source_id)


def count_source(project_id: str, source_id: str) -> int:
    """Number of a source's chunks that are searchable with the current embedding model (no API key needed)."""
    return records.chunk_counts(EMBEDDING_KEY).get(source_id, 0)


def search(project_id: str, query: str, k: int, source_ids: list[str] | None = None,
           operation: str = "search", where: dict | None = None) -> list[tuple[str, float]]:
    """Find the chunks most similar in meaning to a query.

    Args:
        project_id: Project to search in.
        query: Natural-language query; it is embedded with the same model as the chunks.
        k: Maximum number of results.
        source_ids: Optional filter: only search these sources.
        operation: What the search is for; logged as "<operation>/embed_query" in the usage log.
        where: Optional further metadata conditions, e.g. {"chapter": {"$in": [...]}} (structured retrieval, see
            filters.py); combined with the project, model and source filters.

    Returns:
        (chunk_id, relevance) pairs, best first; relevance is the cosine similarity (about 0-1).

    Raises:
        VectorStoreError: If no API key is configured or the search fails.
    """
    vector = _embed_query(project_id, query, operation)
    try:
        results = _store().similarity_search_with_score_by_vector(vector, k=k,
                                                                  filter=search_filter(project_id, source_ids, where))
    except Exception as e:
        raise VectorStoreError(f"Vector search failed: {e}") from e
    return [(doc.id, 1 - distance) for doc, distance in results]  # cosine distance → similarity


def search_filter(project_id: str, source_ids: list[str] | None = None, where: dict | None = None) -> dict:
    """The PGVectorStore filter of a search: the project's chunks embedded with the current key, optionally only of
    some sources and meeting further conditions (chapter, pages)."""
    conditions = [{"project_id": {"$eq": project_id}}, {"embedding_key": {"$eq": EMBEDDING_KEY}}]
    if source_ids:
        conditions.append({"source_id": {"$in": source_ids}})
    if where:
        conditions.append(where)
    return {"$and": conditions}


def similarities(project_id: str, query: str, chunk_ids: list[str], operation: str = "search") -> dict[str, float]:
    """Cosine similarity between a query and the given chunks (for hits found by keyword search, see retrieval.py).

    The query embedding is cached, so after search() with the same query this makes no further embedding call.

    Raises:
        VectorStoreError: If no API key is configured or the lookup fails.
    """
    if not chunk_ids:
        return {}
    query_vector = np.array(_embed_query(project_id, query, operation))
    try:
        stored = records.chunk_embeddings(chunk_ids)
    except Exception as e:
        raise VectorStoreError(f"Vector lookup failed: {e}") from e
    return {chunk_id: float(np.dot(v, query_vector) / (np.linalg.norm(v) * np.linalg.norm(query_vector)))
            for chunk_id, v in ((i, np.array(v)) for i, v in stored.items())}


def health() -> tuple[bool, str]:
    """Status of the vector store for GET /health.

    Returns:
        (ok, detail): ok is False if the API key is missing or the database cannot be read; detail names the store,
        the number of stored chunks and the embedding model.
    """
    try:
        total = records.count_all_chunks()
    except Exception as e:
        return False, f"pgvector · error: {e}"
    if not is_configured():
        return False, f"pgvector · {total} vectors · no OPENROUTER_API_KEY / OPENAI_API_KEY in server/.env"
    return True, f"pgvector · {total} vectors · {EMBEDDING_MODEL} via {PROVIDER}"


# ---------- Internals ----------
def _no_key() -> VectorStoreError:
    return VectorStoreError("No API key set. Add OPENROUTER_API_KEY (or OPENAI_API_KEY) to server/.env and restart the server.")


@cache
def _embeddings() -> OpenAIEmbeddings:
    """The embedding model, via OpenRouter or OpenAI (see module docstring).

    check_embedding_ctx_length=False makes LangChain send plain text instead of pre-tokenized input,
    which OpenRouter does not accept; chunks are far below the model's input limit anyway.
    Each request times out after EMBEDDING_TIMEOUT_SECONDS and is retried up to LLM_MAX_RETRIES times (config.py).
    """
    return OpenAIEmbeddings(model=EMBEDDING_MODEL, api_key=API_KEY, base_url=BASE_URL, check_embedding_ctx_length=False,
                            timeout=EMBEDDING_TIMEOUT_SECONDS, max_retries=LLM_MAX_RETRIES)


@lru_cache(maxsize=256)
def _embed_query(project_id: str, query: str, operation: str) -> list[float]:
    """The query's embedding, cached so that search() and similarities() for one question embed it only once.

    Raises:
        VectorStoreError: If no API key is configured or the embedding fails.
    """
    if not is_configured():
        raise _no_key()
    try:
        vector = _embeddings().embed_query(query)
    except Exception as e:
        raise VectorStoreError(f"Vector search failed: {e}") from e
    usage.record_embedding(f"{operation}/embed_query", EMBEDDING_MODEL, texts=[query], project_id=project_id)
    return vector


@cache
def _pg_engine() -> PGEngine:
    """LangChain's connection to the database, on its own selector event loop in a background thread (see module
    docstring), with a small pool of its own."""
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    threading.Thread(target=loop.run_forever, name="pgvector-loop", daemon=True).start()

    async def make_engine():
        return create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=2)

    return PGEngine.from_engine(asyncio.run_coroutine_threadsafe(make_engine(), loop).result(), loop=loop)


@cache
def _store() -> PGVectorStore:
    """The PGVectorStore over the chunks table (created on first search; it checks the table's columns).

    Raises:
        VectorStoreError: If no API key is configured.
    """
    if not is_configured():
        raise _no_key()
    return PGVectorStore.create_sync(
        engine=_pg_engine(), embedding_service=_embeddings(), table_name="chunks", schema_name="public",
        content_column="content", embedding_column="embedding", id_column="id", metadata_columns=METADATA_COLUMNS,
        metadata_json_column=None)


def _content(chunk: Chunk, title: str | None = None) -> str:
    """What is embedded for a chunk: a "book · chapter" header and its text (the text alone if neither is known)."""
    header = " · ".join(x for x in (title, chunk.location.chapter) if x)
    return f"{header}\n\n{chunk.text}" if header else chunk.text
