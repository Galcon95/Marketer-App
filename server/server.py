"""Marketer App API: entry point. Run with `uv run fastapi dev server.py` (from server/).

Creates the FastAPI app, plugs in the routers of app/api/ and, on startup, loads the saved data from the database.
The code lives in the app package (see README.md, "Project layout"):

    app/core      configuration, chat model, schemas, in-memory state, sign-in and limits, guardrails, usage log,
                  writing style, prompt loading and versions
    app/db        the database (Supabase PostgreSQL with pgvector; SQLAlchemy tables and records)
    app/rag       Phase 1 Knowledge Hub: ingestion, vector store, retrieval, summaries, Q&A, generation
    app/campaign  Phase 2 Content Studio: zero-shot campaign kit
    app/agents    Phase 3 Market Intelligence: the Discussion Relevance Agent (LangGraph), its tools, the Reddit scan
    app/social    the author's Facebook Page (Graph API)
    app/market    Phase 3 Market Intelligence: MCP servers (mcp-book-knowledge at /mcp, mcp-guardrails at /guardrails/mcp)
                  and the app's MCP client for the console (client.py)
    app/api       FastAPI routers, one per area

The prompts are Markdown files in prompts/ (core/prompt_files.py), the limits are in limits.toml.
"""

import logging
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core import logs

logs.setup()  # first, so the imports below already log through it (JSON lines with the request id)

from app.api import (  # noqa: E402
    assets, campaigns, discussions, facebook, health, keys, knowledge, mcp_console, projects, sources,
)
from app.core import api_keys, auth, state, storage, usage  # noqa: E402
from app.db import records  # noqa: E402
from app.core.mcp_auth import RequireMcpAuth  # noqa: E402
from app.market.book_server import book_server  # noqa: E402
from app.market.guard_server import guard_server  # noqa: E402
from app.rag import ingestion, retrieval, summary  # noqa: E402


def restore_data() -> None:
    """Restore the saved data, so it survives server restarts: from the database the projects and their owners, the
    API keys, the sources with their summaries and chunks, generated assets, chats and the usage log.
    Runs on startup (lifespan), not on import, so tests can import this module to check its routes without reading
    the real data. Without the database (DATABASE_URL not set or not reachable) the server does not start: it would
    create a second library for every returning user and accept no API key."""
    state.projects.update(records.load_projects())  # the clients and their owners
    api_keys.load()  # personal API keys for the MCP servers
    ingestion.restore_sources()
    state.assets.update(records.load_assets())
    state.conversations.update(records.load_conversations())
    usage.load()  # totals of all model calls so far, for the console line
    if old := summary.outdated_summaries():
        logging.getLogger("app.startup").warning(
            "%d book summaries were written with older prompts than %s; regenerate them in the Knowledge Hub: %s",
            len(old), summary.PROMPT_VERSION,
            "; ".join(f"{retrieval.source_name(s.source_id) or s.source_id} ({s.prompt_version or 'unversioned'})"
                      for s in old))


# MCP servers over Streamable HTTP; stateless + JSON responses: each request stands alone, no SSE streams.
mcp_app = book_server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True)
guard_app = guard_server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Restore the saved data, then run the MCP session managers while the API runs (a mounted app's own lifespan
    is not started)."""
    restore_data()
    async with AsyncExitStack() as stack:
        for server in (book_server, guard_server):
            await stack.enter_async_context(server.session_manager.run())
        yield


app = FastAPI(title="Marketer App API", lifespan=lifespan)

# Allow the Next.js dev client (port 3000) to call the API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[logs.HEADER],  # so the client can read a response's request id
)
# Added last = outermost: every request (API and MCP) gets its id first, and the id is on every response.
app.add_middleware(logs.RequestIdMiddleware)

# Include the API routers. /health is open; every other endpoint needs a signed-in user (auth.py → 401 otherwise).
app.include_router(health.router)
for module in (projects, sources, knowledge, assets, campaigns, discussions, facebook, mcp_console, keys):
    app.include_router(module.router, dependencies=[Depends(auth.current_user)])

# Last, so the API routes match first. /guardrails before the catch-all "/", which only serves POST/GET /mcp.
# Both need a personal API key or a sign-in token (mcp_auth.py → 401 otherwise).
app.mount("/guardrails", RequireMcpAuth(guard_app))  # → /guardrails/mcp
app.mount("/", RequireMcpAuth(mcp_app))

# run the server
# cd server
# uv run fastapi dev server.py

# see the MCP server with:
# npx @modelcontextprotocol/inspector