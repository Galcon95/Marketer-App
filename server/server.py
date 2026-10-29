"""Marketer App API: entry point. Run with `uv run fastapi dev server.py` (from server/).

Creates the FastAPI app, restores the saved data and plugs in the routers of app/api/. The code
lives in the app package (see README.md, "Project layout"):

    app/core      configuration, chat model, schemas, in-memory state, disk storage, usage log, writing style
    app/rag       Phase 1 Knowledge Hub: ingestion, vector store, retrieval, summaries, Q&A, generation
    app/campaign  Phase 2 Campaign Builder: zero-shot campaign kit
    app/market    Phase 3 Market Intelligence: MCP servers (mcp-book-knowledge at /mcp, mcp-guardrails at /guardrails/mcp)
                  and the app's MCP client for the console (client.py)
    app/agents    Phase 4 Agent Workspace (still empty)
    app/api       FastAPI routers, one per area
"""

import logging
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core import logs

logs.setup()  # first, so the imports below already log through it (JSON lines with the request id)

from app.api import assets, campaigns, health, knowledge, mcp_console, projects, sources  # noqa: E402
from app.core import state, storage, usage  # noqa: E402
from app.market.book_server import book_server  # noqa: E402
from app.market.guard_server import guard_server  # noqa: E402
from app.rag import ingestion, retrieval, summary  # noqa: E402

# Restore uploaded sources (with their chunks) and generated assets from disk, so they survive
# server restarts.
ingestion.restore_sources()
state.assets.update(storage.load_assets())
state.conversations.update(storage.load_conversations())
usage.load()  # totals of all model calls so far (usage.jsonl)
if old := summary.outdated_summaries():
    logging.getLogger("app.startup").warning(
        "%d book summaries were written with older prompts than %s; regenerate them in the Knowledge Hub: %s",
        len(old), summary.PROMPT_VERSION, "; ".join(f"{retrieval.source_name(s.source_id) or s.source_id} ({s.prompt_version or 'unversioned'})"
                                                  for s in old))

# MCP servers over Streamable HTTP; stateless + JSON responses: each request stands alone, no SSE streams.
mcp_app = book_server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True)
guard_app = guard_server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Run the MCP session managers while the API runs (a mounted app's own lifespan is not started)."""
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

# inlcude the API routers
for module in (health, projects, sources, knowledge, assets, campaigns, mcp_console):
    app.include_router(module.router)

# Last, so the API routes match first. /guardrails before the catch-all "/", which only serves POST/GET /mcp.
app.mount("/guardrails", guard_app)  # → /guardrails/mcp
app.mount("/", mcp_app)

# run the server
# cd server
# uv run fastapi dev server.py

# see the MCP server with:
# npx @modelcontextprotocol/inspector