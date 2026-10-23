# Marketer App

A tool for book marketing: a Next.js frontend (`client/`) talks to a FastAPI backend (`server/`), which also
hosts two MCP servers. What is built so far: [FEATURES.md](FEATURES.md).

## Run it locally, step by step

You need **3 terminals**: server, client, and (optionally) the MCP Inspector.

### 0. Once: prerequisites and API key

- [uv](https://docs.astral.sh/uv/) (installs Python 3.11 and the server packages by itself) and [Node.js](https://nodejs.org) (with npm/npx).
- An OpenRouter API key: copy `server/.env.example` to `server/.env` and set `OPENROUTER_API_KEY=...`
  (or set it as a Windows user variable). Without a key the app starts, but nothing can be generated.
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
   and press **Process**. Wait until it shows `ready`. Uploaded books stay in `server/assets/` and survive restarts.
2. Make the **book summary**, try **Ask your book** (the chat), and generate assets with the **Grounded asset generator**.
3. **Campaign Builder**: pick the book, check the brief, press **Generate campaign (zero-shot)** for personas, posts and a blurb.
4. **Market Intelligence**: the MCP tool console (both MCP servers, status, tools, call log).
5. Costs so far: the usage panel in the app, or http://127.0.0.1:8000/usage.

### Stop

Press `Ctrl+C` in each terminal.

## Optional extras

- **Use the books from Claude Code:** `claude mcp add --transport http book-knowledge http://127.0.0.1:8000/mcp`
- **RAG evaluation (RAGAs)**, with the server running: `cd eval`, then `uv run python run_eval.py --limit 3`. See [eval/README.md](eval/README.md).
- **Different server URL** for the client: set `NEXT_PUBLIC_API_URL` (default `http://127.0.0.1:8000`).

More details: [server/README.md](server/README.md) (layout, MCP tools) and [eval/README.md](eval/README.md).

## Quick start (summary)

0. **Once:** `OPENROUTER_API_KEY=...` in `server/.env`.
1. **Server (terminal 1):** `cd server`, then `uv run fastapi dev server.py`. Check http://127.0.0.1:8000/health and http://127.0.0.1:8000/docs in the browser.
2. **Client (terminal 2):** `cd client`, then `npm install` (first time only) and `npm run dev`. Open **http://localhost:3000**.
3. **MCP Inspector (terminal 3):** `npx @modelcontextprotocol/inspector`. Connect with Streamable HTTP to
   `http://127.0.0.1:8000/mcp` (books) or `http://127.0.0.1:8000/guardrails/mcp` (security checks).
4. **See it in action:**
   - Upload the Garden Cities PDF from the repo root and press **Process**.
   - Make the summary, try the chat and the asset generator.
   - Generate a campaign in the Campaign Builder.
   - Call the MCP tools in the Market Intelligence tab.
   - Look at the costs.
5. **Stop:** `Ctrl+C` in each terminal.

Start the server first: the client and the Inspector both need it.
