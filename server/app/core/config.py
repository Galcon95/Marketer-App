"""Configuration of the server: paths, model provider, API key and model names, LangSmith tracing.

Read once on import from environment variables (and server/.env, if present), first match wins:
    OPENROUTER_API_KEY  → models via OpenRouter (default chat "openai/gpt-4o-mini",
                          embeddings "openai/text-embedding-3-large")
    OPENAI_API_KEY      → models via OpenAI directly (default chat "gpt-4o-mini",
                          embeddings "text-embedding-3-large")
    LLM_MODEL           → optional, overrides the chat model
    EMBEDDING_MODEL     → optional, overrides the embedding model
    LLM_TIMEOUT_SECONDS → optional, seconds one chat model request may take before it is retried (default 45)
    EMBEDDING_TIMEOUT_SECONDS → optional, the same for one embedding request (default 30)
    LLM_MAX_RETRIES     → optional, retries of a failed or timed-out model request (default 3)
    MIN_RELEVANCE       → optional, the lowest similarity (0-1) a passage needs to reach the chat model (default 0.3);
                          a question with no passage above it is answered "not covered" without a model call
    RETRIEVAL_MODE      → optional, "dense" (default: vector search) or "hybrid" (vector + BM25 keyword search,
                          fused by rank; see retrieval.py)
    LOG_FORMAT          → optional, "json" (default: one JSON object per log line) or "text" (readable lines)
    LOG_LEVEL           → optional, the lowest level that is logged (default "INFO"; "DEBUG" also logs GET requests)
    DEBUG_MODE=true     → developer debug mode: every graph run is traced in LangSmith (needs LANGSMITH_API_KEY;
                          see tracing.py). Default off; keep it off for customers and in production
    LANGSMITH_PROJECT   → optional, the LangSmith project the traces go to (default "marketer-app")
    SUPABASE_URL        → URL of the Supabase project whose users may sign in (auth.py checks their access tokens
                          with its public signing keys); without it every API request except /health gets 503
    DEFAULT_CLIENT_OWNER → email of the user who owns the default client ("demo-campaign", the data from before
                          sign-in existed) and is the app's admin (app-wide usage, MCP console); see accounts.py
    SUPABASE_SECRET_KEY → the Supabase project's secret key ("sb_secret_..."): the server stores the uploaded books
                          and their covers with it in the private Storage bucket "books" (files.py); never sent to
                          the browser
    DATABASE_URL        → connection string of the PostgreSQL database (Supabase), e.g.
                          "postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres";
                          required: the server does not start without it (see app/db/database.py)
"""

import os
from pathlib import Path

from dotenv import load_dotenv

SERVER_DIR = Path(__file__).resolve().parents[2]  # server/
DATA_DIR = SERVER_DIR / "assets"  # uploads, chunks, vectors, generated assets, usage log

load_dotenv(SERVER_DIR / ".env")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

if os.getenv("OPENROUTER_API_KEY"):
    PROVIDER, API_KEY, BASE_URL = "openrouter", os.getenv("OPENROUTER_API_KEY"), OPENROUTER_BASE_URL
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "openai/text-embedding-3-large")
    LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
else:
    PROVIDER, API_KEY, BASE_URL = "openai", os.getenv("OPENAI_API_KEY"), None
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large")
    LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "45"))
EMBEDDING_TIMEOUT_SECONDS = float(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "30"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))

MIN_RELEVANCE = float(os.getenv("MIN_RELEVANCE", "0.3"))
RETRIEVAL_MODE = "hybrid" if os.getenv("RETRIEVAL_MODE", "dense").strip().lower() == "hybrid" else "dense"

LOG_FORMAT = "text" if os.getenv("LOG_FORMAT", "json").strip().lower() == "text" else "json"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()

DEBUG_MODE = os.getenv("DEBUG_MODE", "false").strip().lower() in ("true", "1", "on", "yes")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT") or os.getenv("LANGCHAIN_PROJECT") or "marketer-app"

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "").strip()
DEFAULT_CLIENT_OWNER = os.getenv("DEFAULT_CLIENT_OWNER", "").strip().lower()


def _sqlalchemy_url(url: str) -> str:
    """The connection string as Supabase shows it ("postgresql://..." or "postgres://..."), with the psycopg driver
    SQLAlchemy should use ("postgresql+psycopg://..."). Other URLs (e.g. sqlite in tests) stay as they are."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


DATABASE_URL = _sqlalchemy_url(os.getenv("DATABASE_URL", "").strip())


def langsmith_key_set() -> bool:
    """True if a LangSmith API key is set (also accepts the older LANGCHAIN_API_KEY name)."""
    return bool(os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY"))


def tracing_enabled() -> bool:
    """True if LangSmith tracing is on: debug mode and a LangSmith API key. LANGSMITH_TRACING plays no part."""
    return DEBUG_MODE and langsmith_key_set()
