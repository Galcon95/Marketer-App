# Instructions for coding agents

Read this before changing anything. It is the project's working agreement for coding agents (Claude Code reads it
through [CLAUDE.md](CLAUDE.md); others read this file). `client/AGENTS.md` adds the Next.js rules for the client.

## What this is

The Marketer App helps independent authors market a book: RAG over the book, a Discussion Relevance Agent, a
Telegram-approved marketing agent for a Facebook Page and a YouTube channel, content generation, two MCP servers.
Overview: [README.md](README.md) · features: [FEATURES.md](FEATURES.md) · security: [SECURITY.md](SECURITY.md) ·
agent design and evals: [docs/AGENT.md](docs/AGENT.md) · Telegram agent: [docs/PAGE_INBOX.md](docs/PAGE_INBOX.md).

| Part | Where | Run | Check |
|---|---|---|---|
| Server (FastAPI, LangChain, LangGraph) | `server/` | `uv run fastapi dev server.py` | `uvx ruff check .` · `uv run pytest -q` |
| Client (Next.js) | `client/` | `npm run dev` | `npm run lint` · `npx tsc --noEmit` · `npm test` |
| Evals (RAG, agent, guard) | `eval/` | see [eval/README.md](eval/README.md) | costs model calls: only when asked |
| Database migrations (Alembic, Supabase) | `server/migrations/` | `uv run alembic upgrade head` | additive only |

## Rules (each one exists because something went wrong without it)

- **AI stack: LangChain family only.** LangChain, LangGraph (agents, with the shared checkpointer), LangSmith
  (tracing); every model through OpenRouter (`app/core/llm.py`). No other agent framework or provider SDK. Images:
  only `gemini-3.1-flash-image` (via OpenRouter).
- **Every prompt lives in `server/prompts/*.md`**, read with `app/core/prompt_files.py`; never a prompt string in
  Python. Rules and file kinds: [server/prompts/README.md](server/prompts/README.md). Register a new prompt with
  `prompts.register(...)` so its version is traced and saved with results.
- **Untrusted text is data.** A reader's comment, a book passage, a web page or a video transcript goes to a model only
  quoted (`guard.quote_untrusted`), after the input guard where it comes from outside. Model output that will be
  posted goes through the output guard and `core/links.py` (only the author's book links stay). The model never gets a
  tool that posts, deletes or sends: publishing is code behind the author's approval.
- **Human in the loop stays.** Nothing is published without the author's "Make it so" (Telegram) or click (app). Do
  not add an automatic posting mode for replies to other people.
- **Secrets only in `server/.env` / `client/.env.local`** (never committed) and in Render/Vercel settings. Never log a
  token or a key; the audit log holds ids and short facts only.
- **No books in git**, not even public-domain ones (`/*.pdf` is ignored); link to a download instead. Cover pictures
  come from the paperback cover PDF, cropped; nothing is written into the book folders.
- **Tests while building: targeted** (the files you touched and their neighbours); **the full suite before every
  commit**; evals only at the end of a feature, when asked. Tests never reach a real service: models, Facebook, Google,
  Telegram and Supabase are faked, the database is in-memory SQLite, tracing is off (`tests/conftest.py`).
- **Client tests on Windows:** run them from `E:\` (upper-case drive letter); from `e:\` Vitest fails with "reading
  config".
- **Local first, then deploy.** Build and test against the local server. Commit, push and deploy only when the user
  says so. Push only to `origin` (never to a course submission remote unless it is named). Render deploys by hand
  (Manual Deploy); Vercel deploys the client on every push to `main`.
- **One Telegram poller.** A local server next to the deployed one runs with `TELEGRAM_POLLING=false`, or two
  servers fight over the bot.
- **Migrations are additive** (new columns with defaults), because Render's running code and the local code share one
  Supabase database. Apply them yourself (`alembic upgrade head`) and say so.
- **Docstrings and comments explain why**, in plain English, like the existing code (module docstrings describe the
  flow; see `app/agents/engagement.py`). Update the docs that describe a feature you change (`docs/`, `FEATURES.md`,
  `SECURITY.md`, `README.md`).

## How to work on a feature

1. **Explore first**: read the module docstrings of the files involved and their tests; `grep` for the setting or
   function across `server/` and `client/` (a setting usually touches schema, table, migration, API, client form, docs).
2. **Plan in steps** the user can test one at a time; agree on the plan before building a larger feature.
3. **Build with tests** next to the code (`server/tests/test_<module>.py`); fakes, not mocks of internals.
4. **Verify**: targeted tests, then `uv run pytest -q` and `uvx ruff check .`; client changes also `npx tsc --noEmit`
   and `npm run lint`. Report failures as they are; do not weaken a test to make it pass.
5. **Review** the diff before committing (Claude Code: `/code-review`; for security-relevant changes
   `/security-review`). CI runs ruff, pytest, ESLint, the type check, Vitest, gitleaks and the dependency audits.
6. **Release** with the `release` skill (`.claude/skills/release/SKILL.md`) when the user says to deploy.
