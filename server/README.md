# Marketer App – Server

FastAPI backend for the marketer app. To start the whole system (server, client, MCP Inspector) step by step,
see the [main README](../README.md).

## Run

```sh
uv run alembic upgrade head        # once, and after every update with a new migration (needs DATABASE_URL)
uv run fastapi dev server.py
```

The server needs Supabase: the database (`DATABASE_URL`) and Storage (`SUPABASE_SECRET_KEY`) in `.env`, see
`.env.example`. Without the database it does not start.

- API: http://127.0.0.1:8000
- Interactive docs: http://127.0.0.1:8000/docs

## Project layout

Imports only go downward: `api` → `agents` / `campaign` / `social` / `market` → `rag` → `core` / `db`.

```
server/
├── server.py           entry point: creates the FastAPI app, restores saved data, includes the routers
├── app/
│   ├── core/           shared basics
│   │   ├── config.py   paths, provider, API key, model names, LangSmith tracing (reads .env)
│   │   ├── llm.py      chat model (ChatOpenAI via OpenRouter), GenerationError, token counts
│   │   ├── prompt_files.py  loads the prompts from prompts/*.md
│   │   ├── prompts.py  prompt versions (a hash of the loaded prompt text)
│   │   ├── guard.py    input checks, prompt-injection scan, quoting as data, output guard
│   │   ├── schemas.py  Pydantic request/response models
│   │   ├── state.py    in-memory stores (projects, sources, chunks, summaries, assets)
│   │   ├── storage.py  upload checks (type, size, checksum), PDF author
│   │   ├── files.py    the books and covers in Supabase Storage (private bucket "books")
│   │   ├── usage.py    tokens and costs of every model call
│   │   └── style.py    "how human" levels, AI-cliché check and rewrite (texts in prompts/)
│   ├── db/             the database (PostgreSQL at Supabase; SQLAlchemy)
│   │   ├── database.py     connection (DATABASE_URL), sessions, DatabaseError
│   │   ├── tables.py       tables: projects, sources, summaries, chunks, assets, conversations,
│   │   │                   discussion_analyses, usage_log; api_keys
│   │   ├── records.py      read and write all records; usage sums and budgets
│   ├── rag/            Phase 1 Knowledge Hub
│   │   ├── ingestion.py    PDF → chapters → chunks → vectors
│   │   ├── vectorstore.py  embeddings in PostgreSQL (pgvector, LangChain PGVectorStore)
│   │   ├── retrieval.py    vector search, prompt context, citations
│   │   ├── summary.py      book summaries (LangGraph map-reduce)
│   │   ├── qa.py           ask your book (LangGraph)
│   │   └── generation.py   single assets, grounded or zero-shot (LangGraph)
│   ├── campaign/       Phase 2 Content Studio: campaign kits
│   │   └── kit.py      zero-shot kit: personas → posts + blurb (LangGraph)
│   ├── market/         Phase 3 Market Intelligence (MCP)
│   │   ├── book_server.py  mcp-book-knowledge: the books as MCP tools (mounted at /mcp)
│   │   └── guard_server.py mcp-guardrails: input validation and prompt-injection checks (/guardrails/mcp)
│   ├── agents/         Discussion Relevance Agent (LangGraph), its tools, the Reddit scan
│   ├── social/         the author's Facebook Page (Graph API)
│   └── api/            FastAPI routers: health, projects, keys, sources, knowledge, assets, campaigns,
│                       discussions, facebook, mcp_console (+ deps.py: ownership, input checks, limits)
├── prompts/            every prompt as a Markdown file (see prompts/README.md)
├── migrations/         Alembic migrations of the database (alembic.ini next to server.py)
└── assets/books/       sample books for trying the app (not committed)
```

## Data storage

All data lives in one Supabase project; the server keeps only configuration (`.env`, `limits.toml`).

| What | Where | Notes |
|---|---|---|
| Projects (clients) and owners | `public.projects` | one project per user (unique `owner_id`) |
| Personal MCP API keys | `private.api_keys` | SHA-256 hashes only; schema not served by the REST API |
| Books (sources) | `public.sources` | status saved, progress in memory; same file once per project |
| Book summaries | `public.summaries` | deleted with the book |
| Chunks and their vectors | `public.chunks` | pgvector, exact cosine search via LangChain `PGVectorStore` |
| Generated assets, chats | `public.assets`, `public.conversations` | nested parts (citations, turns) as JSONB |
| Discussion analyses | `public.discussion_analyses` | the agent's results with reply, citations, tool trace, injection scan |
| Model calls and costs | `public.usage_log` | the budgets of `limits.toml` are sums over it |
| Uploaded PDFs and covers | Storage bucket `books` (private) | `{project}/{source}/book.pdf`, `cover.png`; max 50 MB |
| Books over 50 MB (optional) | `server/data/books/` on the server's disk (`LOCAL_FILES_DIR`) | the user chooses "Store on server" when uploading; max 500 MB (`max_server_upload_mb`); not backed up by Supabase |
| Schema version | `private.alembic_version` | `uv run alembic current` |

**Security.** Only the server reaches the data: it connects as the database owner and uses the secret key for
Storage. Every table has row-level security without a policy, and the browser's roles (`anon`, `authenticated`)
have no privileges on them (migration 0007); the `private` schema and the bucket are not reachable with the
public key at all. A new table's migration must do the same (`ENABLE ROW LEVEL SECURITY`, `REVOKE ALL ... FROM
anon, authenticated`).

**Schema changes** go through Alembic: change `app/db/tables.py`, then
`uv run alembic revision --autogenerate -m "..."`, check the file, `uv run alembic upgrade head`;
`uv run alembic check` confirms the database matches the code.

**Working copies in memory.** On startup the server loads the records into memory (`core/state.py`) and writes
every change to the database first. That is fine for one server process; several processes would need to read
from the database directly.

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

Every request needs `Authorization: Bearer …`: a personal API key (`mk_…`, made in the app's keys panel) or the
app's access token (`core/mcp_auth.py`). The tools serve the caller's own library; only localhost Host/Origin
headers are accepted.

## MCP server: mcp-guardrails

Security checks for text sent to a language model, at `http://127.0.0.1:8000/guardrails/mcp`. The logic lives
in `app/core/guard.py` (pure functions, no model calls), so the API can call it directly too.

| Tool | Returns |
|---|---|
| `validate_input(text, kind)` | cleaned text, ok, problems (empty, too long, hidden characters, repetition); limits per kind |
| `check_prompt_injection(text)` | passed (false on high risk), risk none/low/high, findings with rule and excerpt, advice |
| `wrap_untrusted(passages)` | passages in `<passage n="...">` tags, the system prompt rule, passages flagged as risky |

The injection check is rule-based (override phrases, role changes, prompt leaks, fake role markers, exfiltration
links, hidden characters): it catches common attacks, not every one. It flags none of the current book chunks.
The same sign-in as the book server is needed.

The app's endpoints call `guard.py` directly, including two checks that are not MCP tools: `scan_third_party`
(other people's text from Reddit, Facebook and pasted discussions: flagged, not blocked) and `check_output` (the
agent's drafted replies: injection phrases that got through, links not from the book; Facebook posting refuses
a text with a likely injection).

## Tests

```sh
uv run pytest        # from server/; 565 tests, about 15 seconds
```

`tests/` needs no model, no API key and no network: the chat model, the vector search, Tavily and the Facebook Graph
API are faked, and Storage is an in-memory store. Among them:

- guardrails, the injection scan of third-party text and the output guard (`test_guard*.py`), the platform check,
  citations, chapter detection, structured retrieval filters, the prompt files and their loader (`test_prompt_files.py`)
- the Discussion Relevance Agent (graph routing, tool limits, schemas, API), the Reddit scan, the Facebook client and
  endpoints (`test_discussion_*.py`, `test_api_discussions.py`, `test_*facebook.py`)
- sign-in on every route, ownership (another user's data answers 404), limits and budgets, API keys and MCP sign-in,
  uploads (types, duplicates, the 50 MB limit, larger books on the server's disk), deleting a book with what belongs only to it, the database layer
- API tests showing that bad requests are rejected before any model call (`test_api_guardrails.py`)

The quality of the model's answers is measured separately (`../eval/`): RAGAs for "Ask your book" and an agent eval
for the Discussion Relevance Agent.

