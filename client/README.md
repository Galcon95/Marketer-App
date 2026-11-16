# Marketer App: client

The web interface of the Marketer App: Next.js 16 (App Router), React 19 and TypeScript. It signs the user in with
Supabase Auth and sends every request to the FastAPI server in [`../server`](../server), which does all of the
work: RAG, content generation, the Discussion Relevance Agent and the MCP servers. The client holds no model keys
and no business logic.

How to run the whole app (server and client): [../README.md](../README.md).

## Run

```sh
cp .env.example .env.local   # then fill in the Supabase URL and publishable key
npm install                  # first time, and after package.json changes
npm run dev                  # http://localhost:3000 (the server must run on http://127.0.0.1:8000)
```

| Variable | Meaning |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | The Supabase project URL (sign-in). |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | The publishable key. It is public (sent to the browser); the secret key never goes here. |
| `NEXT_PUBLIC_API_URL` | Optional. URL of the FastAPI server, default `http://127.0.0.1:8000`. |

## Layout

| Path | What it is |
|---|---|
| `app/page.tsx` | The only app page: renders `AppShell`. |
| `app/login/`, `app/auth/confirm/` | Sign-in page and the link from the confirmation email. |
| `proxy.ts` | Runs before every page request: refreshes the Supabase session and sends visitors who are not signed in to `/login`. It only guards pages; the server checks the access token of every API request itself. |
| `components/AppShell.tsx` | Sidebar navigation between the three phases, sign-out, the usage and API-key drawers. |
| `components/phases/` | The phases: `KnowledgeHub` (upload and process books, summary, chat), `ContentStudio` (single assets with citations; its Campaign kit is `CampaignBuilder`) and `Community` (Discussion agent, Reddit scan, Facebook Page); `McpServers` is the MCP tool console (sidebar: Integrations; admin only). |
| `components/` | Building blocks: `DiscussionAgent`, `DiscussionCard`, `ToolCallCard` (the agent's tool trace), `RedditScan`, `Facebook*`, `InjectionBadge` (flags third-party text that looks like prompt injection), `KeysPanel` (MCP API keys) and others. |
| `lib/api.ts` | Typed API client for the server: every endpoint, error handling and helpers for labels, citations and URLs. |
| `lib/useApi.ts`, `lib/supabase.ts` | React hook for API calls; Supabase browser client. |
| `app/styles/` | Design tokens and the app's stylesheet (see `../app-design-system/`). |

## Checks

```sh
npm run lint         # ESLint
npx tsc --noEmit     # type check (on a fresh checkout run `npx next typegen` first)
npm test             # Vitest, about 1 second
```

`tests/api.test.ts` (21 tests) covers the helpers in `lib/api.ts` (book titles, labels, citation markers, URLs) and
the API client's error handling, with `fetch` replaced by a stub so no server is needed. All three checks also run in
GitHub Actions on every push and pull request (`.github/workflows/ci.yml`).
