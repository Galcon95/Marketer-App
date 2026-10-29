"""Vector store for RAG retrieval, built on LangChain: chunk embeddings in Chroma.

    Chunk ──OpenAIEmbeddings──► vector ──► Chroma collection per project and model (server/assets/chroma/)
    query ──OpenAIEmbeddings──► vector ──► nearest chunks by cosine similarity (relevance 0-1)

Each vector is stored under its chunk id with metadata source_id, chunk_id, chapter and page, so a
source's vectors can be replaced or deleted and searches can be limited to some sources. The chunk
files (.chunks.jsonl) stay the source of truth: the vectors can always be rebuilt from them by
re-indexing a source. The collection name contains the embedding model, because vectors of
different models cannot be compared: after switching models, sources must be re-indexed.

Provider, API key and embedding model come from core/config.py (OPENROUTER_API_KEY or
OPENAI_API_KEY, optional EMBEDDING_MODEL).
"""

import logging
import re
from collections.abc import Callable
from functools import cache

import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

from app.core import config, usage
from app.core.config import (API_KEY, BASE_URL, DATA_DIR, EMBEDDING_MODEL, EMBEDDING_TIMEOUT_SECONDS, LLM_MAX_RETRIES,
                             PROVIDER)
from app.core.schemas import Chunk

logger = logging.getLogger(__name__)

CHROMA_DIR = DATA_DIR / "chroma"
EMBED_BATCH = 64  # chunks per embedding request; also the step size of the progress updates

class VectorStoreError(Exception):
    """A vector store problem whose message can be shown to the user (missing key, API error, ...)."""

# ---------- Public API ----------
def is_configured() -> bool:
    """True if an API key (OpenRouter or OpenAI) is set, i.e. texts can be embedded."""
    return bool(API_KEY)


def add_chunks(project_id: str, source_id: str, chunks: list[Chunk], on_progress: Callable[[float], None] | None = None) -> None:
    """Embed the chunks of a source and store them, replacing the source's previous vectors.

    Chunk ids are stable (chk_<source>_<n>), so re-indexing overwrites existing vectors in place
    (upsert) and searches keep working meanwhile; vectors of chunks that no longer exist are removed
    afterwards.

    Args:
        project_id: Project the source belongs to (selects the collection).
        source_id: Source the chunks belong to.
        chunks: All chunks of the source.
        on_progress: Optional callback with the fraction of chunks embedded (0.0-1.0).

    Raises:
        VectorStoreError: If no API key is configured or embedding/storing fails.
    """
    store = _store(project_id, with_embeddings=True)
    try:
        for start in range(0, len(chunks), EMBED_BATCH):
            batch = chunks[start:start + EMBED_BATCH]
            store.add_documents([_to_document(c) for c in batch], ids=[c.id for c in batch])
            usage.record_embedding("embed_chunks", EMBEDDING_MODEL, tokens=sum(c.token_count for c in batch),
                                   project_id=project_id, source_id=source_id)
            if on_progress:
                on_progress(min(start + EMBED_BATCH, len(chunks)) / len(chunks))
        new_ids = {c.id for c in chunks}
        stale = [i for i in _source_ids(project_id, source_id) if i not in new_ids]
        if stale:
            _store(project_id).delete(ids=stale)
    except VectorStoreError:
        raise
    except Exception as e:
        raise VectorStoreError(f"Embedding failed: {e}") from e


def delete_source(project_id: str, source_id: str) -> None:
    """Remove all vectors of a source (no API key needed).

    Args:
        project_id: Project the source belongs to.
        source_id: Source whose vectors to remove.
    """
    ids = _source_ids(project_id, source_id)
    if ids:
        _store(project_id).delete(ids=ids)


def count_source(project_id: str, source_id: str) -> int:
    """Number of vectors stored for a source (no API key needed)."""
    return len(_source_ids(project_id, source_id))


def search(project_id: str, query: str, k: int, source_ids: list[str] | None = None,
           operation: str = "search", where: dict | None = None) -> list[tuple[str, float]]:
    """Find the chunks most similar in meaning to a query.

    Args:
        project_id: Project to search in.
        query: Natural-language query; it is embedded with the same model as the chunks.
        k: Maximum number of results.
        source_ids: Optional filter: only search these sources.
        operation: What the search is for; logged as "<operation>/embed_query" in the usage log.
        where: Optional further Chroma metadata conditions, e.g. {"chapter": {"$in": [...]}} (structured
            retrieval, see filters.py); combined with the source filter.

    Returns:
        (chunk_id, relevance) pairs, best first; relevance is the cosine similarity (about 0-1).

    Raises:
        VectorStoreError: If no API key is configured or the search fails.
    """
    store = _store(project_id, with_embeddings=True)
    conditions = [c for c in ({"source_id": {"$in": source_ids}} if source_ids else None, where) if c]
    combined = None if not conditions else conditions[0] if len(conditions) == 1 else {"$and": conditions}
    try:
        results = store.similarity_search_with_relevance_scores(query, k=k, filter=combined)
        usage.record_embedding(f"{operation}/embed_query", EMBEDDING_MODEL, texts=[query], project_id=project_id)
    except Exception as e:
        raise VectorStoreError(f"Vector search failed: {e}") from e
    return [(doc.metadata["chunk_id"], score) for doc, score in results]


def health() -> tuple[bool, str]:
    """Status of the vector store for GET /health.

    Returns:
        (ok, detail): ok is False if the API key is missing or Chroma cannot be opened; detail
        names the store, the number of stored vectors and the embedding model.
    """
    try:
        total = sum(_client().get_collection(c.name).count() for c in _client().list_collections())
    except Exception as e:
        return False, f"chroma · error: {e}"
    if not is_configured():
        return False, f"chroma · {total} vectors · no OPENROUTER_API_KEY / OPENAI_API_KEY in server/.env"
    return True, f"chroma · {total} vectors · {EMBEDDING_MODEL} via {PROVIDER}"


# ---------- Internals ----------
@cache
def _client() -> chromadb.ClientAPI:
    """The persistent Chroma client (data in CHROMA_DIR), shared by all collections. Telemetry is off."""
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(CHROMA_DIR), settings=chromadb.Settings(anonymized_telemetry=False))


@cache
def _embeddings() -> OpenAIEmbeddings:
    """The embedding model, via OpenRouter or OpenAI (see module docstring).

    check_embedding_ctx_length=False makes LangChain send plain text instead of pre-tokenized input,
    which OpenRouter does not accept; chunks are far below the model's input limit anyway.
    Each request times out after EMBEDDING_TIMEOUT_SECONDS and is retried up to LLM_MAX_RETRIES times (config.py).
    """
    return OpenAIEmbeddings(model=EMBEDDING_MODEL, api_key=API_KEY, base_url=BASE_URL, check_embedding_ctx_length=False,
                            timeout=EMBEDDING_TIMEOUT_SECONDS, max_retries=LLM_MAX_RETRIES)


@cache
def _store(project_id: str, with_embeddings: bool = False) -> Chroma:
    """The LangChain Chroma store of a project's collection, created on first use with cosine distance.

    Args:
        project_id: Project whose collection to open; the collection is named
            "<project_id>--<model>", e.g. "demo-campaign--text-embedding-3-large".
        with_embeddings: True for operations that embed text (add, search); requires the API key.
            Maintenance operations (get, delete, count) work without it.

    Raises:
        VectorStoreError: If with_embeddings is True and no API key is configured.
    """
    if with_embeddings and not is_configured():
        raise VectorStoreError("No API key set. Add OPENROUTER_API_KEY (or OPENAI_API_KEY) to server/.env and restart the server.")
    model = re.sub(r"[^a-zA-Z0-9._-]", "-", EMBEDDING_MODEL.split("/")[-1])
    return Chroma(
        collection_name=f"{project_id}--{model}",
        embedding_function=_embeddings() if with_embeddings else None,
        client=_client(),
        collection_configuration={"hnsw": {"space": "cosine"}},
    )


def _source_ids(project_id: str, source_id: str) -> list[str]:
    """Ids of all vectors stored for a source."""
    return _store(project_id).get(where={"source_id": source_id}, include=[])["ids"]


def _to_document(chunk: Chunk) -> Document:
    """A LangChain Document for a chunk: its text plus the metadata used for filtering and lookup.

    Chroma metadata values cannot be None, so a missing chapter or page is left out.
    """
    metadata = {"source_id": chunk.source_id, "chunk_id": chunk.id,
                "chapter": chunk.location.chapter, "page": chunk.location.page}
    return Document(page_content=chunk.text, metadata={k: v for k, v in metadata.items() if v is not None})
