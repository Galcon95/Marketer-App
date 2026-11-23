"""Configuration of the server: model provider, API key and model names, LangSmith tracing.

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
    IMAGE_PROVIDER      → optional, who makes the ad images (core/images.py): "openrouter" (default; the same key as
                          the chat model, needs OPENROUTER_API_KEY). A local provider ("comfyui") is planned
    IMAGE_MODEL         → optional, the OpenRouter image model (default "google/gemini-3.1-flash-image"; it must
                          take an image in, the book cover, and give images out through the chat endpoint)
    IMAGE_TIMEOUT_SECONDS → optional, seconds one image request may take (default 120); a failed one is retried once
    MIN_RELEVANCE       → optional, the lowest similarity (0-1) a passage needs to reach the chat model (default 0.3);
                          a question with no passage above it is answered "not covered" without a model call
    RETRIEVAL_MODE      → optional, "dense" (default: vector search) or "hybrid" (vector + BM25 keyword search,
                          fused by rank; see retrieval.py)
    LOG_FORMAT          → optional, "json" (default: one JSON object per log line) or "text" (readable lines)
    LOG_LEVEL           → optional, the lowest level that is logged (default "INFO"; "DEBUG" also logs GET requests)
    DEBUG_MODE=true     → developer debug mode: every graph run is traced in LangSmith (needs LANGSMITH_API_KEY;
                          see tracing.py). Default off; keep it off for customers and in production
    TAVILY_API_KEY      → optional, key of the Tavily search API ("tvly-..."): the Reddit scan finds threads with it
                          (agents/discussion_scan.py); without it the scan answers 503, everything else works
    FACEBOOK_PAGE_ID, FACEBOOK_PAGE_TOKEN → optional, the admin's own Facebook Page and its Page access token
                          (Graph API, see social/facebook.py): read its posts and comments, publish a post, reply to a
                          comment. Only for the admin (DEFAULT_CLIENT_OWNER) and the Page inbox agent; every other
                          user connects their own Page (FACEBOOK_APP_ID below)
    FACEBOOK_APP_ID     → optional, id of the Meta app: with it, FACEBOOK_APP_SECRET and TOKEN_ENCRYPTION_KEY every
                          user can connect their own Page with Facebook Login (social/page_connections.py)
    TOKEN_ENCRYPTION_KEY → optional, a Fernet key (44 characters; make one with `uv run python -c "from
                          cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`): the users' Page
                          tokens are saved encrypted with it (core/secret_box.py). Changing it disconnects every Page
    PUBLIC_API_URL      → optional, the address under which browsers reach this server (default
                          "http://localhost:8000"): Facebook sends the user back to PUBLIC_API_URL/facebook/oauth/callback,
                          which must be a "Valid OAuth Redirect URI" of the Meta app
    CLIENT_ORIGINS      → optional, comma-separated origins of the web client (default "http://localhost:3000,
                          http://127.0.0.1:3000"): CORS, and where the Facebook Login may send the user back to
    FACEBOOK_APP_SECRET → optional, secret of the Meta app the token belongs to: every Graph request then carries an
                          appsecret_proof (Meta's protection against a stolen token being used elsewhere)
    FACEBOOK_GRAPH_VERSION → optional, the Graph API version (default "v27.0")
    GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET → optional, the OAuth client ("Web application") of a Google Cloud project
                          with the YouTube Data API v3: with them and TOKEN_ENCRYPTION_KEY every user can connect their
                          own YouTube channel with Google sign-in (social/channel_connections.py). Its authorized
                          redirect URI must be PUBLIC_API_URL/youtube/oauth/callback
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID → optional, the author's Telegram bot and their chat with it (Bot API, see
                          social/telegram.py): the agent sends proposed replies there and the author approves them;
                          messages from any other chat are ignored. Without both, Telegram is off
    FACEBOOK_INBOX_BOOKS → optional, comma-separated book ids (src_...) of one client: the Page inbox agent
                          (agents/page_inbox.py) answers readers on the Facebook Page and viewers on the YouTube channel
                          the books' owner connected in the app from the best fitting of them
    FACEBOOK_INBOX_INTERVAL → optional, the default schedule until the books' owner saves one in the app
                          (agents/automation.py): minutes between the inbox worker's looks at the Page (default 30;
                          0 = only when the author sends /next in Telegram)
    LANGSMITH_PROJECT   → optional, the LangSmith project the traces go to (default "marketer-app")
    SUPABASE_URL        → URL of the Supabase project whose users may sign in (auth.py checks their access tokens
                          with its public signing keys); without it every API request except /health gets 503
    DEFAULT_CLIENT_OWNER → email of the user who owns the default client ("demo-campaign", the data from before
                          sign-in existed) and is the app's admin (app-wide usage, MCP console); see accounts.py
    SUPABASE_SECRET_KEY → the Supabase project's secret key ("sb_secret_..."): the server stores the uploaded books
                          and their covers with it in the private Storage bucket "books" (files.py); never sent to
                          the browser
    COVERS_DIR          → optional, folder of the author's own cover pictures (default server/assets/covers): a picture
                          named like a book's file ("My-Book.png" or ".jpg" for "My-Book.pdf") becomes its cover
    LOCAL_FILES_DIR     → optional, folder on the server's disk for books larger than Supabase Storage accepts, when
                          the user chooses "store on this server" (default server/data/books; see files.py)
    DATABASE_URL       → connection string of the PostgreSQL database (Supabase), e.g.
                          "postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres";
                          required: the server does not start without it (see app/db/database.py)
"""

import os
import re
from pathlib import Path

from dotenv import load_dotenv

SERVER_DIR = Path(__file__).resolve().parents[2]  # server/

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

IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER", "openrouter").strip().lower() or "openrouter"
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "google/gemini-3.1-flash-image").strip() or "google/gemini-3.1-flash-image"
IMAGE_TIMEOUT_SECONDS = float(os.getenv("IMAGE_TIMEOUT_SECONDS", "120"))

MIN_RELEVANCE = float(os.getenv("MIN_RELEVANCE", "0.3"))
RETRIEVAL_MODE = "hybrid" if os.getenv("RETRIEVAL_MODE", "dense").strip().lower() == "hybrid" else "dense"

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()

FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID", "").strip()
FACEBOOK_PAGE_TOKEN = os.getenv("FACEBOOK_PAGE_TOKEN", "").strip()
FACEBOOK_APP_SECRET = os.getenv("FACEBOOK_APP_SECRET", "").strip()
FACEBOOK_GRAPH_VERSION = os.getenv("FACEBOOK_GRAPH_VERSION", "v27.0").strip() or "v27.0"
FACEBOOK_APP_ID = os.getenv("FACEBOOK_APP_ID", "").strip()
TOKEN_ENCRYPTION_KEY = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()
PUBLIC_API_URL = (os.getenv("PUBLIC_API_URL", "").strip() or "http://localhost:8000").rstrip("/")
CLIENT_ORIGINS = [o.strip().rstrip("/") for o in (os.getenv("CLIENT_ORIGINS", "").strip()
                  or "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()]

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_CHAT_ID: int | None = int(_chat_id) if re.fullmatch(r"-?\d+", _chat_id) else None
FACEBOOK_INBOX_BOOKS = [s.strip() for s in os.getenv("FACEBOOK_INBOX_BOOKS", "").split(",") if s.strip()]
FACEBOOK_INBOX_INTERVAL = max(0.0, float(os.getenv("FACEBOOK_INBOX_INTERVAL", "30") or 0))

LOG_FORMAT = "text" if os.getenv("LOG_FORMAT", "json").strip().lower() == "text" else "json"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()

DEBUG_MODE = os.getenv("DEBUG_MODE", "false").strip().lower() in ("true", "1", "on", "yes")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT") or os.getenv("LANGCHAIN_PROJECT") or "marketer-app"

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "").strip()
DEFAULT_CLIENT_OWNER = os.getenv("DEFAULT_CLIENT_OWNER", "").strip().lower()
LOCAL_FILES_DIR = Path(os.getenv("LOCAL_FILES_DIR", "").strip() or SERVER_DIR / "data" / "books")
# The author's own cover pictures, named like the book's file ("My-Book.pdf" → "My-Book.png" or ".jpg"): used instead of
# the cover taken from the PDF (rag/ingestion.py folder_cover). Not committed (server/assets/ is git-ignored).
COVERS_DIR = Path(os.getenv("COVERS_DIR", "").strip() or SERVER_DIR / "assets" / "covers")


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
