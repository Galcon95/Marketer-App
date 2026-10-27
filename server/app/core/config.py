"""Configuration of the server: paths, model provider, API key and model names, LangSmith tracing.

Read once on import from environment variables (and server/.env, if present), first match wins:
    OPENROUTER_API_KEY  → models via OpenRouter (default chat "openai/gpt-4o-mini",
                          embeddings "openai/text-embedding-3-large")
    OPENAI_API_KEY      → models via OpenAI directly (default chat "gpt-4o-mini",
                          embeddings "text-embedding-3-large")
    LLM_MODEL           → optional, overrides the chat model
    EMBEDDING_MODEL     → optional, overrides the embedding model
    DEBUG_MODE=true     → developer debug mode: every graph run is traced in LangSmith (needs LANGSMITH_API_KEY;
                          see tracing.py). Default off; keep it off for customers and in production
    LANGSMITH_PROJECT   → optional, the LangSmith project the traces go to (default "marketer-app")
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


DEBUG_MODE = os.getenv("DEBUG_MODE", "false").strip().lower() in ("true", "1", "on", "yes")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT") or os.getenv("LANGCHAIN_PROJECT") or "marketer-app"


def langsmith_key_set() -> bool:
    """True if a LangSmith API key is set (also accepts the older LANGCHAIN_API_KEY name)."""
    return bool(os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY"))


def tracing_enabled() -> bool:
    """True if LangSmith tracing is on: debug mode and a LangSmith API key. LANGSMITH_TRACING plays no part."""
    return DEBUG_MODE and langsmith_key_set()
