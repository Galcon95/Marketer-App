# Marketer App

A tool for book marketing: a Next.js frontend (`client/`) talks to a FastAPI backend (`server/`), which also
hosts two MCP servers. What is built so far: [FEATURES.md](FEATURES.md). The app's agent, the **Discussion
Relevance Agent** (purpose, use cases, how it works, technical decisions): [docs/AGENT.md](docs/AGENT.md).

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
- Optional: your own **Facebook Page** (`FACEBOOK_PAGE_ID`, `FACEBOOK_PAGE_TOKEN`, `FACEBOOK_APP_SECRET`), for
  answering readers' comments and publishing posts. Setup steps are in the comments in `server/.env.example`.
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
You can also call both MCP servers inside the app, in the **Market Intelligence** tab, without the Inspector.

### 4. See it in action

1. **Knowledge Hub**: upload a PDF book (e.g. `Garden-Cities-of-To-Morrow_Ebenezer-Howard.pdf` in the repo root)
   and press **Process**. Wait until it shows `ready`. Uploaded books are stored in Supabase and survive restarts.
2. Make the **book summary** and try **Ask your book** (the chat).
3. **Content Studio**: in **Single asset**, write a blurb, post, newsletter, ... from the book with citations; in
   **Campaign kit**, check the brief and press **Generate campaign (zero-shot)** for personas, posts and a blurb.
4. **Market Intelligence → Discussions** (the agent):
   - **Paste a discussion**: pick the book, paste a post (e.g. from Reddit, plus some replies), choose the platform
     and press **Analyse**. The agent answers *contribute* (with a reply grounded in the book, citations and advice
     on naming the book), *more context needed* or *skip*, with its reason. Open the **tool trace** to see which
     searches it made. Edit the reply and press **Copy for posting**.
   - **Scan Reddit** (needs `TAVILY_API_KEY`): enter a topic and optionally subreddits; the threads come back ranked
     high / medium / low for the book. **Analyse** loads one into the agent.
   - Try a trap: a thread that only shares a keyword with the book (e.g. "garden" in a gardening question) should be
     *skip*.
5. **Market Intelligence → MCP servers**: the MCP tool console (both MCP servers, status, tools, call log; admin only).
6. Costs so far: the usage panel in the app, or http://127.0.0.1:8000/usage.

### Stop

Press `Ctrl+C` in each terminal.

## Optional extras

- **Use the books from Claude Code:** `claude mcp add --transport http book-knowledge http://127.0.0.1:8000/mcp`
- **RAG evaluation (RAGAs)**, with the server running: `cd eval`, then `uv run python run_eval.py --limit 3`. See [eval/README.md](eval/README.md).
- **Agent evaluation**, with the server running: `cd eval`, then `uv run python run_agent_eval.py` (12 labelled
  discussions; `--no-judge` for decisions and checks only). See [eval/README.md](eval/README.md).
- **Different server URL** for the client: set `NEXT_PUBLIC_API_URL` (default `http://127.0.0.1:8000`).

More details: [docs/AGENT.md](docs/AGENT.md) (the agent), [server/README.md](server/README.md) (layout, MCP tools)
and [eval/README.md](eval/README.md).

## Quick start (summary)

0. **Once:** Supabase values and `OPENROUTER_API_KEY` in `server/.env` and `client/.env.local`, then `uv run alembic upgrade head` in `server/`.
1. **Server (terminal 1):** `cd server`, then `uv run fastapi dev server.py`. Check http://127.0.0.1:8000/health and http://127.0.0.1:8000/docs in the browser.
2. **Client (terminal 2):** `cd client`, then `npm install` (first time only) and `npm run dev`. Open **http://localhost:3000**.
3. **MCP Inspector (terminal 3):** `npx @modelcontextprotocol/inspector`. Connect with Streamable HTTP to
   `http://127.0.0.1:8000/mcp` (books) or `http://127.0.0.1:8000/guardrails/mcp` (security checks).
4. **See it in action:**
   - Upload the Garden Cities PDF from the repo root and press **Process**.
   - Make the summary and try the chat.
   - In the Content Studio, generate an asset (Single asset) and a campaign (Campaign kit).
   - In Market Intelligence → Discussions, paste a discussion (or scan Reddit) and let the agent analyse it.
   - Call the MCP tools in Market Intelligence → MCP servers.
   - Look at the costs.
5. **Stop:** `Ctrl+C` in each terminal.

Start the server first: the client and the Inspector both need it.
