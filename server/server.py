"""Marketer App API: entry point. Run with `uv run fastapi dev server.py` (from server/).

Creates the FastAPI app, restores the saved data and plugs in the routers of app/api/. The code
lives in the app package (see README.md, "Project layout"):

    app/core      configuration, chat model, schemas, in-memory state, disk storage, usage log, writing style
    app/rag       Phase 1 Knowledge Hub: ingestion, vector store, retrieval, summaries, Q&A, generation
    app/campaign  Phase 2 Campaign Builder: zero-shot campaign kit
    app/market    Phase 3 Market Intelligence (MCP), app/agents Phase 4 (both still empty)
    app/api       FastAPI routers, one per area
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import assets, campaigns, health, knowledge, projects, sources
from app.core import state, storage, usage
from app.rag import ingestion

# Restore uploaded sources (with their chunks) and generated assets from disk, so they survive
# server restarts.
ingestion.restore_sources()
state.assets.update(storage.load_assets())
usage.load()  # totals of all model calls so far (usage.jsonl)

app = FastAPI(title="Marketer App API")

# Allow the Next.js dev client (port 3000) to call the API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (health, projects, sources, knowledge, assets, campaigns):
    app.include_router(module.router)
