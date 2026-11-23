# Marketer App

[![CI](https://github.com/Galcon95/Marketer-App/actions/workflows/ci.yml/badge.svg)](https://github.com/Galcon95/Marketer-App/actions/workflows/ci.yml)

**Goal, problem and how it works.** Independent authors know their book but rarely have time to market it, and the
best readers are found in online discussions where people already ask about the book's topic. Joining those
discussions by hand is slow, and replying with ads gets authors ignored or banned. The Marketer App helps an author
answer only where the book really helps. The author uploads the book, and the app indexes it for retrieval (RAG:
LangChain, pgvector, hybrid search). For a discussion pasted in or found by a Reddit scan, the **Discussion Relevance
Agent** (LangGraph) searches the book in a bounded loop and makes one of three decisions: *contribute* (with a
drafted reply grounded in cited passages, and advice on whether to name the book), *more context needed*, or *skip*.
The author edits and approves every reply; nothing is posted automatically. On 12 labelled discussions, the agent
made an acceptable decision in 11 (exactly the expected one in 10), skipped all 3 keyword traps, cited the book in
every drafted reply and reached a RAGAs faithfulness of 0.83
([eval results](docs/AGENT.md#8-quality-how-it-is-measured)).

Around the agent, the app also writes summaries, posts and campaign kits from the book with citations, answers
readers on a Facebook Page (with approval in Telegram) and under the videos of a YouTube channel, and offers the book and the guardrails as two MCP servers.

- Features: [FEATURES.md](FEATURES.md)
- The agent (purpose, use cases, how it works, technical decisions, evaluation): [docs/AGENT.md](docs/AGENT.md)
- Stack: Next.js client (`client/`), FastAPI server (`server/`), Supabase (Auth, PostgreSQL with pgvector, Storage),
  models via OpenRouter, tracing in LangSmith
- Quality: 675 server tests (pytest) and 21 client tests (Vitest), run by CI with ruff, ESLint and a type check;
  RAG and agent evaluations in [eval/](eval/README.md)

## Run it locally, step by step

You need **3 terminals**: server, client, and (optionally) the MCP Inspector.

### 0. Once: prerequisites and keys

- [uv](https://docs.astral.sh/uv/) (installs Python 3.11 and the server packages by itself) and [Node.js](https://nodejs.org) (with npm/npx).
- A [Supabase](https://supabase.com) project: it holds the sign-in, the database (PostgreSQL with pgvector) and
  the uploaded books (Storage). Copy `server/.env.example` to `server/.env` and set `SUPABASE_URL`,
  `DATABASE_URL` (Connect → Direct → Session pooler), `SUPABASE_SECRET_KEY` (API Keys → Secret keys) and
  `DEFAULT_CLIENT_OWNER` (your sign-in email); copy `client/.env.example` to `client/.env.local` with the
  project's URL and publishable key. The comments in both files say where to find each value.
- An OpenRouter API key: `OPENROUTER_API_KEY=...` in `server/.env` (or a Windows user variable). Without a key
  the app starts, but nothing can be generated.
- Create the tables and the Storage bucket: `cd server`, then `uv run alembic upgrade head` (again after every
  update that brings a new migration).
- Optional: a [Tavily](https://tavily.com) API key (free plan) for the **Reddit scan**: `TAVILY_API_KEY=tvly-...` in
  `server/.env`. Without it the scan answers 503; pasting a discussion still works.
- Optional: **Facebook Pages**, for answering readers' comments and publishing posts. With a Meta app
  (`FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET`) and `TOKEN_ENCRYPTION_KEY`, every user connects their own Page under
  **Integrations → Facebook Page** (Facebook Login). The admin can instead set one Page directly (`FACEBOOK_PAGE_ID`,
  `FACEBOOK_PAGE_TOKEN`). Setup steps are in the comments in `server/.env.example`.
- Optional: **YouTube channels**, for answering comments under the videos. With a Google Cloud OAuth client
  (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, YouTube Data API v3 enabled) and `TOKEN_ENCRYPTION_KEY`, every user
  connects their own channel under **Integrations → YouTube channel** (Google sign-in). Setup steps are in the comments
  in `server/.env.example`.
- Optional: LangSmith tracing, see the comments in `server/.env.example`.

### 1. Start the server (terminal 1)

```sh
cd server
uv run fastapi dev server.py
```

The first start installs the packages, so it takes a moment. It is ready when it prints `Application startup complete`.

Check it in the browser:
- http://127.0.0.1:8000/health: all services should be `ok: true`
- http://127.0.0.1:8000/docs: the API with every endpoint, to try out

### 2. Start the client (terminal 2)

```sh
cd client
npm install        # only the first time (and after package.json changes)
npm run dev
```

Open the app: **http://localhost:3000**

### 3. Open the MCP Inspector (terminal 3, optional)

```sh
npx @modelcontextprotocol/inspector
```

It opens in the browser by itself (http://localhost:6274). If it doesn't, use the link with the token that it prints.
Then connect with **Transport type** `Streamable HTTP` and one of these URLs:

| MCP server | URL |
|---|---|
| mcp-book-knowledge (the books) | `http://127.0.0.1:8000/mcp` |
| mcp-guardrails (security checks) | `http://127.0.0.1:8000/guardrails/mcp` |

Press **Connect**, then **List Tools**, then pick a tool and **Run Tool**. The server from step 1 must be running.
You can also call both MCP servers inside the app, under **Integrations → MCP servers** in the sidebar, without the Inspector.

### 4. See it in action

1. **Knowledge Hub**: upload a PDF book and press **Process**. Books are not stored in this repository; for a free
   sample, download Ebenezer Howard's *Garden Cities of To-Morrow* (public domain) from
   [Project Gutenberg](https://www.gutenberg.org/ebooks/search/?query=garden+cities+of+to-morrow) (open the HTML
   version and print it to PDF in the browser). Wait until it shows `ready`. Uploaded books are stored in Supabase and survive restarts.
   A book can be at most **50 MB** (the largest file Supabase Storage accepts on the free plan). For a larger PDF,
   compress it (it is usually the images; the app only reads the text) or split it into parts and upload each part as
   its own book.
2. Make the **book summary** and try **Ask your book** (the chat).
3. **Content Studio**: in **Single asset**, write a blurb, post, newsletter, ... from the book with citations; in
   **Campaign kit**, check the brief and press **Generate campaign (zero-shot)** for personas, posts and a blurb.
4. **Community** (the agent):
   - **Paste a discussion**: pick the book, paste a post (e.g. from Reddit, plus some replies), choose the platform
     and press **Analyse**. The agent answers *contribute* (with a reply grounded in the book, citations and advice
     on naming the book), *more context needed* or *skip*, with its reason. Open the **tool trace** to see which
     searches it made. Edit the reply and press **Copy for posting**.
   - **Scan Reddit** (needs `TAVILY_API_KEY`): enter a topic and optionally subreddits; the threads come back ranked
     high / medium / low for the book. **Analyse** loads one into the agent.
   - Try a trap: a thread that only shares a keyword with the book (e.g. "garden" in a gardening question) should be
     *skip*.
5. **Integrations → MCP servers** (sidebar): the MCP tool console (both MCP servers, status, tools, call log; admin only).
6. Costs so far: the usage panel in the app, or http://127.0.0.1:8000/usage.

### Stop

Press `Ctrl+C` in each terminal.

## Optional extras

- **Use the books from Claude Code:** `claude mcp add --transport http book-knowledge http://127.0.0.1:8000/mcp`
- **RAG evaluation (RAGAs)**, with the server running: `cd eval`, then `uv run python run_eval.py --limit 3`. See [eval/README.md](eval/README.md).
- **Agent evaluation**, with the server running: `cd eval`, then `uv run python run_agent_eval.py` (12 labelled
  discussions; `--no-judge` for decisions and checks only). See [eval/README.md](eval/README.md).
- **Facebook Page and YouTube inbox with approval in Telegram:** set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` and
  `FACEBOOK_INBOX_BOOKS` in `server/.env`, plus `FACEBOOK_PAGE_*` for the Page and/or connect your YouTube channel in
  the app, then send `/next` to your bot. See [docs/PAGE_INBOX.md](docs/PAGE_INBOX.md).
- **Different server URL** for the client: `npm run dev` uses the local server, `npm run dev:render` the one on Render (a badge next to the page title shows which); any other: set `NEXT_PUBLIC_API_URL`.

More details: [docs/AGENT.md](docs/AGENT.md) (the agent), [server/README.md](server/README.md) (layout, MCP tools)
and [eval/README.md](eval/README.md).

## Quick start (summary)

0. **Once:** Supabase values and `OPENROUTER_API_KEY` in `server/.env` and `client/.env.local`, then `uv run alembic upgrade head` in `server/`.
1. **Server (terminal 1):** `cd server`, then `uv run fastapi dev server.py`. Check http://127.0.0.1:8000/health and http://127.0.0.1:8000/docs in the browser.
2. **Client (terminal 2):** `cd client`, then `npm install` (first time only) and `npm run dev`. Open **http://localhost:3000**.
3. **MCP Inspector (terminal 3):** `npx @modelcontextprotocol/inspector`. Connect with Streamable HTTP to
   `http://127.0.0.1:8000/mcp` (books) or `http://127.0.0.1:8000/guardrails/mcp` (security checks).
4. **See it in action:**
   - Upload a PDF book (e.g. *Garden Cities of To-Morrow*, see step 4 above) and press **Process**.
   - Make the summary and try the chat.
   - In the Content Studio, generate an asset (Single asset) and a campaign (Campaign kit).
   - In Community, paste a discussion (or scan Reddit) and let the agent analyse it.
   - Call the MCP tools under Integrations → MCP servers.
   - Look at the costs.
5. **Stop:** `Ctrl+C` in each terminal.

Start the server first: the client and the Inspector both need it.
