# Marketer App – Features Implemented So Far

A tool for book marketing. A Next.js frontend (`client/`) talks to a FastAPI backend (`server/`). The AI parts use LangChain, LangGraph and LangSmith, with models reached through OpenRouter.

Status as of commit `e114f04` (2026-10-22).

| Phase | Name | Status |
|---|---|---|
| 1 | Knowledge Hub (RAG) | ✅ Built |
| 2 | Campaign Builder (zero-shot) | ✅ Built |
| 3 | Market Intelligence (MCP) | 🟡 2 MCP servers + tool console built, leads table still a placeholder |
| 4 | Agent Workspace | ⬜ Placeholder UI only |

---

## Phase 1 – Knowledge Hub (RAG over your books)

### Upload & ingestion
- Upload PDF books with a progress bar (`POST /projects/{id}/sources`).
- Ingestion runs in the background: PDF → chapters → token-based chunks (500 tokens with 80 overlap, so tiny pieces get merged) → embeddings → Chroma.
- Chapters come from the PDF's table of contents. PDFs without one (e.g. many Project Gutenberg files) get them from heading lines in the text (`CHAPTER IV.` plus its title line, or `PART TWO` / `BOOK I` when there are no chapters); the printed contents page is ignored.
- The Project Gutenberg license after the e-book's end marker becomes its own section instead of being glued to the last chapter.
- Live progress through the statuses `queued → chunking → embedding → ready` (or `failed`), saved so it survives restarts.
- Sources are processed one at a time, because PyMuPDF is not thread-safe.
- **Process / Re-index / Retry** actions, plus deleting a source.
- Book covers are extracted from the PDF and shown in the library.
- The author is read from the PDF's metadata when the file name has none; it is used in prompts, citations, the MCP tools and the Campaign Builder.
- Chunk browser: page through a book's chunks with chapter and page info.
- Open the original PDF at the cited page (PDF page links).

### Book summaries (LangGraph map-reduce)
- Summarizes every chapter in parallel, then combines them into a book overview with key themes.
- Skips front and back matter (contents, index, license and similar).
- Books without any detected chapters are summarized in sections of about 6,000 tokens ("Section 1", "Section 2", ...).
- Saved next to the book as `.summary.json`, and can be regenerated.
- Grounded generation uses the summary as background.

### Ask your book (LangGraph Q&A chat with history)
- Ask a question about one book or all of them. The answer cites passages as `[n]`, each with chapter, page and quote.
- Says so when the books don't answer the question.
- **Conversation history:** follow-up questions can refer to earlier turns ("and who collects that money?").
  - Query translation: a `condense` step rewrites a follow-up into a standalone question before retrieval, shown in the GUI as "Searched for: …".
  - The answer prompt gets the last 4 turns as chat messages (earlier answers shortened, citation markers removed); only the current passages may be cited.
- Chats are saved in `server/assets/conversations/` and survive restarts: **New chat**, **Past chats** (reopen or delete), at most 50 questions per chat.
- Questions are checked with the guardrails functions in code, on every question: cleaned, at most 4000 characters (422, room for a pasted post), likely prompt injections blocked (400).
- **Tool calling** (LangChain `bind_tools`, one round, no loop): besides the passages, the model may call
  - `list_books`: the library (titles, authors, themes), for questions about the library itself
  - `check_platform_fit`: a pure calculation of characters, words, hashtags, preview length and AI clichés against a platform's rules
  - `draft_social_post`: writes a grounded post with the generator, saves it as an asset and checks it for the platform
  - Graph: `answer ─(tool calls?)─► tools ─► respond`; `respond` runs with `tool_choice="none"`, so there is never a second round. At most 3 calls per answer; invalid arguments or unknown tools become error results for the model.
  - Book content is deliberately not a tool: the fixed RAG step already supplies the passages. Security checks are not tools either.
  - The chat shows each tool call as a card (tool, arguments, duration, full result).

### Semantic search
- `POST /projects/{id}/search` returns the top-k passages with similarity scores.

### Grounded asset generator (LangGraph)
- Asset types: **blurb, social post, social reply, video script, YouTube video page, newsletter, ad copy, lead magnet, persona**.
- Platforms: X, LinkedIn, Instagram, Facebook, TikTok and YouTube, each with its own length and style rules for posts, replies and short videos.
- Tones: neutral, inspiring, friendly, professional, punchy, literary. Lengths: short, standard, long.
- **Grounded** mode retrieves excerpts and cites them. **Zero-shot** mode writes without excerpts.
- **Social replies**: the LLM first turns the post plus your angle into a search query, then writes a reply that sounds like a person in the conversation.
- Citations are renumbered, and only the excerpts the model actually used are kept.

### "How human" (humanize slider, 0–100)
- Adds more and more style guidance as the value rises and raises the temperature slightly.
- Detects AI clichés ("dive into", "tapestry", "game-changer", emoji piles and more).
- From 60 up, rewrites the flagged parts once and keeps the facts, quotes and `[n]` markers.

### Asset library
- Every generated asset is saved. You can edit it, delete it, or copy it without the citation markers.
- **Verify**: checks each sentence of an asset against the books by similarity and marks it as verified or not found.

---

## Phase 2 – Campaign Builder (zero-shot campaign kit)

A LangGraph pipeline turns one book brief into a whole kit:

```
personas ─┬─► 5 social posts ─┬─► polish (AI-cliché check / rewrite)
          └─► blurb ──────────┘
```

- **3 reader personas** (structured output): snapshot, what they read, why this book appeals to them, platforms, and a message that works.
- **5 social posts**, one per angle (hook, teaser, question, behind the scenes, call to action). Each is written for one persona, on a platform where that persona can be reached.
- **1 blurb** of 120–180 words for the back cover or store page.
- Posts and blurb are generated in parallel, then polished with the same humanize logic as Phase 1.
- **Brief form**: picking a library book fills in the title, author, themes and premise from its summary. A "new book" option lets you type everything yourself.
- **Audience focus**: General readers, personas made earlier for that book, or a custom audience.
- The author comes from the book: from its file name, or else from the PDF's metadata (author field, or "…, by Name" in a Project Gutenberg title).
- Past campaigns are listed, and kits are saved as assets.

---

## Phase 3 – Market Intelligence: `mcp-book-knowledge` MCP server

The books are served as an MCP server (Streamable HTTP, official `mcp` SDK) at `http://127.0.0.1:8000/mcp`. It runs inside the API process, so newly processed books show up right away.

| Tool | Returns | Model call |
|---|---|---|
| `list_books` | ids, titles, authors, themes, whether a summary exists | none |
| `search_book(query, book_id?, k)` | passages with chapter, page and score | embedding |
| `get_book_summary(book_id)` | overview, themes, chapter summaries | none |
| `ask_book(question, book_id?)` | a cited answer | embedding + LLM |

- All tools are annotated as read-only. Expected errors are returned as `ToolError`, and the message lists the valid book ids.
- Local use only: there is no authentication, and only localhost Host/Origin headers are accepted.
- MCP clients can connect to it, for example MCP Inspector, Claude Code (`claude mcp add`) or Claude Desktop (through `mcp-remote`).

### `mcp-guardrails` MCP server (security)

Served at `http://127.0.0.1:8000/guardrails/mcp`. Unlike the book server, it is also meant for the app itself. The logic is in `app/core/guard.py`: pure functions with no model calls (about 0.5 ms per text).

| Tool | Returns |
|---|---|
| `validate_input(text, kind)` | cleaned text and problems: empty, too long (limits per kind: question 1000, chat message 2000, search query 500, brief 4000, social post 3000, asset text 12000), hidden characters, repetition |
| `check_prompt_injection(text)` | risk none / low / high, with findings: override phrases, role changes, prompt leaks, fake role markers, hiding from the user, exfiltration links, hidden characters |
| `wrap_untrusted(passages)` | passages in `<passage>` tags (tags inside the text neutralized), the "treat as data" system prompt rule, and the flagged passages |

- Tested on all book chunks: none flagged.
- Not wired into the app's endpoints yet.

### MCP tool console (Market Intelligence tab)

The app acts as a real **MCP client** (official `mcp` SDK `Client`, Streamable HTTP). It talks to its own servers exactly as Claude Desktop would.

- **Server cards** (`GET /mcp-servers`): live status, description, number of tools, endpoint, audience (external only vs. app + external) and latency. Servers are checked in parallel; an offline server shows its error.
- **Tool console**, like the MCP Inspector: pick a server and a tool. The form is generated from the tool's input schema (text, numbers, selects, lists with one item per line, JSON). **Run tool** (`POST /mcp-servers/{name}/call`) shows the result as JSON with status and duration. Tool errors, timeouts and offline servers come back as error results instead of failing the page.
- **Call log** (`GET /mcp-calls`): the last 50 calls in the design system's `call_tool:` log format; click a line to see its result again. Kept in memory only.
- The list of servers the GUI shows is `SERVERS` in `server/app/market/client.py`.
- The leads table is still a placeholder.

---

## Phase 4 – Agent Workspace

- Placeholder UI only: Strategist → Copywriter → Auditor → Human checkpoint cards, an agent console and a review panel.
- No backend yet (`server/app/agents/` is empty).

---

## Cross-cutting features

### Usage & cost tracking
- A LangChain callback logs every LLM call: input and output tokens, and the exact cost in USD reported by OpenRouter (estimated when that isn't available).
- Embedding tokens are counted with tiktoken and priced.
- Each call is appended to `server/assets/usage/usage.jsonl` and printed to the console with running totals.
- The top bar shows the total cost and tokens. Clicking it opens the **LLM usage & costs** drawer with the call history.

### Observability
- LangSmith tracing (`summarize_book`, `generate_campaign`, generation runs) whenever `LANGSMITH_TRACING` is set.

### Persistence
- Sources, chunks, summaries, assets and chats are kept in memory and restored from disk when the server starts.
- There is one client ("My library", internally the project `demo-campaign`). Several clients are planned once a database (PostgreSQL) is added.
- Book PDFs are never committed (`.gitignore`).

### API & health
- `GET /health` reports the status of the API, the vector DB and the LLM, which the sidebar shows.
- `GET /usage`, project endpoints, and interactive docs at `/docs`.

### Frontend / UI
- Next.js app shell: a sidebar with pipeline and library navigation, the current client ("My library") and system status. Phase tabs, a mobile menu, and a light/dark theme toggle.
- Uses the **BookCraft design system** (`app-design-system/`): tokens, a Tailwind preset, React primitives, web components and component docs.
- Not built yet: the sidebar's Asset Library, Audiences and Settings pages, and the Export button (disabled).

---

## Tech stack
- **Backend:** Python, FastAPI, uv, LangChain, LangGraph, LangSmith, Chroma, PyMuPDF, tiktoken, `mcp` SDK
- **Models:** chat and embedding models through OpenRouter (OpenAI-compatible)
- **Frontend:** Next.js, React, TypeScript, lucide-react, BookCraft design system
