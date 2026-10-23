# Marketer App – Server

FastAPI backend for the marketer app. To start the whole system (server, client, MCP Inspector) step by step,
see the [main README](../README.md).

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
│   ├── market/         Phase 3 Market Intelligence (MCP)
│   │   ├── book_server.py  mcp-book-knowledge: the books as MCP tools (mounted at /mcp)
│   │   └── guard_server.py mcp-guardrails: input validation and prompt-injection checks (/guardrails/mcp)
│   ├── agents/         Phase 4 Agent Workspace, not built yet
│   └── api/            FastAPI routers: health, projects, sources, knowledge, assets, campaigns (+ deps.py)
└── assets/             data (not committed): uploads, chroma, generated, usage
```

## MCP server: mcp-book-knowledge

While the API runs, the Knowledge Hub's books are also available as an MCP server (Streamable HTTP,
official `mcp` SDK) at `http://127.0.0.1:8000/mcp`:

| Tool | Returns | Model call |
|---|---|---|
| `list_books` | book ids, titles, authors, themes, whether a summary exists | none |
| `search_book(query, book_id?, k=5)` | best passages with chapter, page and similarity | embedding |
| `get_book_summary(book_id)` | overview, themes, chapter summaries | none |
| `ask_book(question, book_id?)` | an answer with [n] citations | embedding + LLM |

Try it:

```sh
npx @modelcontextprotocol/inspector                    # Transport "Streamable HTTP", URL http://127.0.0.1:8000/mcp
claude mcp add --transport http book-knowledge http://127.0.0.1:8000/mcp   # use the books from Claude Code
```

Local use only: no authentication; only localhost Host/Origin headers are accepted.

## MCP server: mcp-guardrails

Security checks for text sent to a language model, at `http://127.0.0.1:8000/guardrails/mcp`. The logic lives
in `app/core/guard.py` (pure functions, no model calls), so the API can call it directly too.

| Tool | Returns |
|---|---|
| `validate_input(text, kind)` | cleaned text, ok, problems (empty, too long, hidden characters, repetition); limits per kind |
| `check_prompt_injection(text)` | risk none/low/high, findings with rule and excerpt, advice |
| `wrap_untrusted(passages)` | passages in `<passage n="...">` tags, the system prompt rule, passages flagged as risky |

The injection check is rule-based (override phrases, role changes, prompt leaks, fake role markers, exfiltration
links, hidden characters): it catches common attacks, not every one. It flags none of the current book chunks.

## Tests

```sh
uv run pytest        # from server/; about 3 seconds
```

`tests/` holds unit tests of the logic that needs no model or API key: the guardrails (`test_guard.py`), the
platform check (`test_platforms.py`), citation handling, the prompt format of passages and chapter detection
(`test_rag_helpers.py`), plus API tests showing that bad requests are rejected before any model call, including
the rate limit (`test_api_guardrails.py`). The quality of the model's answers is measured separately with RAGAs
(`../eval/`).

