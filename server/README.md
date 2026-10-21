# Marketer App – Server

FastAPI backend for the marketer app.

## Run

```sh
uv run fastapi dev server.py
```

- API: http://127.0.0.1:8000
- Interactive docs: http://127.0.0.1:8000/docs

## Project layout

Imports only go downward: `api` → `campaign` → `rag` → `core`.

```
server/
├── server.py           entry point: creates the FastAPI app, restores saved data, includes the routers
├── app/
│   ├── core/           shared basics
│   │   ├── config.py   paths, provider, API key, model names, LangSmith tracing (reads .env)
│   │   ├── llm.py      chat model (ChatOpenAI via OpenRouter), GenerationError, token counts
│   │   ├── schemas.py  Pydantic request/response models
│   │   ├── state.py    in-memory stores (projects, sources, chunks, summaries, assets)
│   │   ├── storage.py  files on disk: uploads, chunks, summaries, covers, generated assets
│   │   ├── usage.py    tokens and costs of every model call
│   │   └── style.py    platform rules, tones, "how human" levels, AI-cliché check and rewrite
│   ├── rag/            Phase 1 Knowledge Hub
│   │   ├── ingestion.py    PDF → chapters → chunks → vectors
│   │   ├── vectorstore.py  embeddings in Chroma
│   │   ├── retrieval.py    vector search, prompt context, citations
│   │   ├── summary.py      book summaries (LangGraph map-reduce)
│   │   ├── qa.py           ask your book (LangGraph)
│   │   └── generation.py   single assets, grounded or zero-shot (LangGraph)
│   ├── campaign/       Phase 2 Campaign Builder
│   │   └── kit.py      zero-shot kit: personas → posts + blurb (LangGraph)
│   ├── market/         Phase 3 Market Intelligence (MCP), not built yet
│   ├── agents/         Phase 4 Agent Workspace, not built yet
│   └── api/            FastAPI routers: health, projects, sources, knowledge, assets, campaigns (+ deps.py)
└── assets/             data (not committed): uploads, chroma, generated, usage
```
