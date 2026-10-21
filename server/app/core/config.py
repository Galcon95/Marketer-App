"""Configuration of the server: paths, model provider, API key and model names, LangSmith tracing.

Read once on import from environment variables (and server/.env, if present), first match wins:
    OPENROUTER_API_KEY  → models via OpenRouter (default chat "openai/gpt-4o-mini",
                          embeddings "openai/text-embedding-3-large")
    OPENAI_API_KEY      → models via OpenAI directly (default chat "gpt-4o-mini",
                          embeddings "text-embedding-3-large")
    LLM_MODEL           → optional, overrides the chat model
    EMBEDDING_MODEL     → optional, overrides the embedding model
    LANGSMITH_TRACING=true + LANGSMITH_API_KEY → runs are traced in LangSmith (LangChain picks these up itself)
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


def tracing_enabled() -> bool:
    """True if LangSmith tracing is switched on and has an API key (also accepts the older LANGCHAIN_* names)."""
    on = (os.getenv("LANGSMITH_TRACING") or os.getenv("LANGCHAIN_TRACING_V2") or "").lower() == "true"
    return on and bool(os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY"))
