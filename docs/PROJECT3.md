# Project 3: what is implemented

How the Marketer App meets the Project 3 (agents) requirements, as of 2026-11-12.
Details: [AGENT.md](AGENT.md) (the agent) · [FEATURES.md](../FEATURES.md) (the whole app) · [README](../README.md) (run it).

---

## 1. Required tasks

| Requirement | Done | Where |
|---|---|---|
| **Clear purpose** | ✅ | The Discussion Relevance Agent decides whether an online discussion is worth joining with one book (`contribute` / `more_context` / `skip`) and drafts a cited reply. [AGENT.md §1](AGENT.md#1-purpose) |
| **Why it's useful** | ✅ | Authors are told to "join the conversation", but most threads are a poor fit and promotional replies backfire. The agent filters and writes from the book. |
| **Target users** | ✅ | Indie and self-published authors, small publishers and book marketers, mainly non-fiction. |
| **Main features** | ✅ | Research tool loop, decision, grounded draft, platform and AI-cliché check, humanizer rewrite, citations. Reddit scan to find threads. Answering readers on the author's own Facebook Page and writing new posts for it from the book. |
| **User interactions** | ✅ | Book, platform, angle, tone, "how human" slider; edit the reply, copy for posting, delete; tool trace; Reply / Publish on Facebook on click; "Write a new post" (post or reader question) on the Facebook tab. |
| **User interface** | ✅ | Next.js app, Market Intelligence → Discussions (Paste / Scan Reddit / My Facebook Page). Phase 4 is clearly marked as planned. |
| **Tools and libraries** | ✅ | LangGraph, LangChain (`bind_tools`, structured output), LangSmith, OpenRouter, Tavily, pgvector, FastAPI, Supabase. |
| **Error handling** | ✅ | Tool errors returned to the model, loop limits, retries and timeouts, schema validation, budgets, clear HTTP errors. [AGENT.md §7](AGENT.md#7-error-handling-and-edge-cases) |
| **Real-world usage** | ✅ | Sign-in, one library per user, per-user budgets and rate limits, data in Supabase, 579 server tests, eval on 12 labelled cases. |
| **Documentation: how to use** | ✅ | [README](../README.md) "See it in action", [AGENT.md §2](AGENT.md#2-how-to-use-it) |
| **Documentation: use cases** | ✅ | [AGENT.md §3](AGENT.md#3-common-use-cases): 7 cases from the eval set |
| **Documentation: technical decisions** | ✅ | [AGENT.md §6](AGENT.md#6-technical-decisions) |

## 2. Optional tasks

### Easy
| Task | Done | How |
|---|---|---|
| Personality | ✅ | 6 tones (neutral, inspiring, friendly, professional, punchy, literary) and the "how human" slider; from 60 on, a humanizer rewrites every social post and reply so it doesn't read as AI; own Page mode writes as the author in the first person. |
| Interface for model settings | 🟡 | The "how human" slider sets the temperature (0.5–1.0) and the style guidance; no direct temperature or max-token fields. |
| Choose the LLM | ❌ | One model, set by `LLM_MODEL` (OpenRouter makes switching a config change). |
| Interactive help / chatbot guide | ❌ | |
| Critique by another LLM | 🟡 | A review's prompt suggestion was tested and rejected on evidence (AI-cliché list, [FEATURES.md](../FEATURES.md) "Prompt engineering choices"). |

### Medium
| Task | Done | How |
|---|---|---|
| Token usage and costs | ✅ | Every model call logged with tokens and exact OpenRouter cost; usage drawer in the top bar; per-user totals. |
| Memory | ✅ | Short-term: the chat's last 4 turns plus a follow-up rewrite. Long-term: chats, analyses and assets saved per user in Postgres. |
| Extra function tool calling an external API | 🟡 | External APIs are integrated (Tavily for Reddit, Facebook Graph API), but called from code, not as LLM tools. |
| Auth and personalisation | ✅ | Supabase Auth, one library per user, personal API keys for the MCP servers. |
| Feedback loop with ratings | ❌ | Planned ([AGENT.md §10](AGENT.md#10-possible-improvements)). |
| 5 tools with enable/disable UI | 🟡 | 5 LLM tools exist (chat: `list_books`, `check_platform_fit`, `draft_social_post`; agent: `get_book_profile`, `search_book_material`), plus 7 MCP tools; no on/off switches. |
| Multi-model support | ❌ | |
| Security guard + developer settings apart from the user | ✅ | Input checks, prompt-injection detection, untrusted text quoted as data, rate limits and budgets, a guardrails MCP server; LangSmith and debug settings only in `server/.env` (debug mode), never in the UI. |

### Hard
| Task | Done | How |
|---|---|---|
| Agentic RAG | ✅ | The agent decides what to search in the book, how often, and when to stop (`search_book_material` in a loop). |
| LLM observability | ✅ | LangSmith traces of every graph run, with prompt version and request id (debug mode). |
| Evaluation report (RAGAs) | ✅ | RAG eval (13 questions, 5 runs) and agent eval (12 discussions: decisions, checks, RAGAs faithfulness, LLM judge), HTML reports. |
| External data sources | ✅ | Reddit threads via Tavily; comments from the author's Facebook Page via the Graph API. |
| Agent that learns from feedback | ❌ | |

**Bonus requirement (≥ 2 medium + 1 hard): met.** 4 medium (plus 2 partial) and 4 hard.

### Beyond the list
- Two **MCP servers** (book knowledge, guardrails) with sign-in, and an MCP client console in the app.
- **Structured retrieval** (book, chapter and page filters taken from the question), a relevance floor, and contextual chunk headers, all measured with RAGAs.
- **Prompt versions** from a hash of all prompt text, saved with every result.
- **Every prompt in a Markdown file** (`server/prompts/*.md`, loaded by `core/prompt_files.py`), none in Python code.
- **Humanizer for social media texts**: AI clichés and sentence patterns ("this isn't just X, it's Y") are found in
  code; from "how human" 60 on, every post, reader question and reply is rewritten once by the model, longer formats
  only when clichés were found.

---

## 3. Cheat sheet for the review

### The problem in one sentence
Authors should take part in online discussions to reach readers, but they can't check every thread, and replies
that sound like ads backfire. The agent finds out *whether* the book has something real to add and *what* to say,
with citations, and leaves posting to the author.

### How agents work (in this app)
An agent is an LLM that **chooses its next action** in a loop: reason → call a tool → observe the result → decide
again, until it is done. A chain or pipeline has fixed steps instead.

### Agent types, with examples from the app
| Type | Example in the app |
|---|---|
| Chain / pipeline (fixed steps) | Campaign kit, book summaries (map-reduce), Reddit scan |
| Router / single tool round | Ask your book: the model may call tools once, then must answer |
| ReAct tool loop | The agent's `research` step |
| Workflow with an agentic step | The Discussion agent as a whole: loop for research, fixed nodes for decide, draft, check |
| Plan-and-execute | Not used: the task is small |
| Multi-agent | Planned (Phase 4): Strategist → Copywriter → Auditor → human |

### Function calling, in five steps
1. `model.bind_tools(tools)`: the tools' JSON schemas (from signature and docstring) go with the request.
2. The model answers with text **or** `tool_calls` (name + JSON arguments).
3. A conditional edge routes: tool calls and limits not reached → run tools; otherwise → assess.
4. `run_tool_calls` runs each call and returns one `ToolMessage` per call id. Errors become text the model can
   react to, and results are wrapped in `<tool_result>` as data.
5. Back to the model. Limits: 4 model calls, 6 tool calls, 12,000 characters per result.

### Prompt engineering vs. RAG vs. agent
- **Prompt only:** everything needed is in the input → campaign kit from a brief.
- **RAG:** the answer is in your documents and one search is enough → Ask your book.
- **Agent:** what to look up depends on the input and on earlier results → discussion research.
- Rule of thumb: use the simplest option that works. Agents cost more and are harder to test.

### Code organisation
`server/app/`: `agents/` (graph, tools, scan) · `rag/` (ingestion, retrieval, QA, generation) · `api/` (FastAPI
routes, one file per area) · `core/` (LLM, guard, limits, auth, prompts, usage) · `db/` (SQLAlchemy tables,
records) · `social/` (Facebook) · `market/` (MCP servers and client). `server/prompts/` (all prompts as Markdown),
Alembic migrations, `tests/` (579), `eval/` as a separate project.

### Security
- Untrusted text (discussions, Reddit threads, Facebook comments, book passages, tool results) is only ever
  **quoted as data** under a "never obey" rule; the author's own instructions are checked for prompt injection.
- Reddit threads, Facebook comments and pasted discussions are **scanned for prompt injection**: flagged in the UI,
  saved with the analysis, and a security note goes to the model. Not blocked, because the author doesn't control
  that text.
- **Output guard** on every reply: injection phrases or links not from the book are flagged; Facebook posting
  refuses an injected text (defence in depth: input scan → quoting → output check → human click).
- Sign-in on every route and MCP server; another user's data answers 404; API keys stored only as hashes.
- Per-user rate limit and budgets ($1/day, $10/month), app-wide $20/day.
- Nothing posts by itself: Facebook writes only on a click, admin only, once.
- The agent's tools have no book argument, so the model can't reach another library.

### Error scenarios to name
Book not processed (409) · injection in the angle (400) · injection in a thread or comment (flagged, note to the
model) · injected text in a reply (warning; Facebook refuses, 422) · too long (422) · model loops (limits) · unknown tool or
bad arguments (error result) · no passage (forced *skip*) · invalid structured output (retry, then 502) · timeout
(3 retries, then 504) · budget used up (429) · Tavily or Facebook down (503/502) · Facebook Page not reachable (the tab shows Meta's reason and how to fix it) ·
save fails (500).

### Eval results to quote (agent, 2026-11-10)
11/12 right decisions, 3/3 traps skipped, all replies cited and within limits, injection ignored, faithfulness
0.83, relevance 1.00, tone 0.88, about 14k tokens and 14.5 s per discussion. Measured before the humanizer rewrote
every reply (2026-11-12): a re-run is due.

### Known problems (be honest)
1. It never asks for more context: a fragment got *contribute*.
2. One borderline reply added claims not in the passages (faithfulness 0.44).
3. It advises against naming the book even when a reader asks for a recommendation.
4. 12 eval cases are few; the judge is also an LLM (`gpt-4o-mini`).
5. Reddit only through Tavily (no votes or dates; some threads only as snippets).
6. One model, no fallback; no feedback loop yet.
7. The Facebook connection depends on Meta: on 2026-11-12 Meta's automatic checks blocked the new developer app
   ("API access blocked") until the account was checked; the app then showed the reason instead of hiding the tab.
8. The humanizer costs one more model call per post or reply.

### Improvements to suggest
Re-run the agent eval with the humanizer · feedback ratings used as few-shot examples · a code rule for `more_context` on short fragments · more eval cases
from real threads · model choice and a fallback in debug mode · multi-book research · the Phase 4 multi-agent
workflow · tool on/off switches.

### Demo order (about 10 minutes)
1. Knowledge Hub: a processed book, its summary, one question in Ask your book (citations, tool card).
2. Discussions → Scan Reddit: a topic, ranked threads, **Analyse** one.
3. The result: decision, reason, cited reply, **tool trace**; edit and copy.
4. A trap (gardening thread for *Garden Cities*) → *skip*.
5. My Facebook Page: a reader's comment, answered as the author, Reply on Facebook; **Write a new post** from the
   book with the "how human" slider, then Publish.
6. Usage drawer (costs), a LangSmith trace, the agent eval report.
