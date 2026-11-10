# Discussion Relevance Agent

The agent of the Marketer App: it tells an author whether an online discussion is a good place to contribute from
their book and, if so, drafts a reply that is grounded in that book.

Code: [`server/app/agents/`](../server/app/agents/) · UI: Market Intelligence → **Discussions** ·
Evaluation: [`eval/run_agent_eval.py`](../eval/run_agent_eval.py) · Overview of the whole app: [FEATURES.md](../FEATURES.md)

---

## 1. Purpose

### The problem
Authors, especially self-published and small-press authors, are told to market by "joining the conversation" on
Reddit, LinkedIn, YouTube, forums and their own Facebook Page. In practice this goes wrong in two ways:

- **Most threads are a poor fit.** A keyword match ("AI", "garden", "tax") says little about whether the book has
  something real to add. Checking every thread by hand takes time the author doesn't have.
- **Replies read like ads.** Communities, Reddit above all, punish self-promotion. A reply only helps when it
  answers what was actually asked and brings a concrete idea, argument or example.

### What the agent does
For **one discussion** and **one book**, it answers two questions:

1. *Is this a good opportunity?* It returns one of three recommendations with the reason:
   - `contribute`: the book can add something substantive;
   - `more_context`: the pasted text is too fragmentary to judge, and the agent says what to copy in addition;
   - `skip`: the book has nothing real to add, or a reply would only be advertising.
2. *What would a good reply say?* Only for `contribute`, the agent writes a reply for the platform, written only
   from passages it found in the book. Each claim is cited, and the agent advises whether naming the book would help
   the readers or look like an ad.

The author stays in control: they edit the reply, copy it (citation markers removed) and post it themselves. The
only exception is the author's own Facebook Page, where a **Reply on Facebook** button posts it, again only on a
click.

### Target users
- **Indie and self-published authors** who do their own marketing and have little time.
- **Small publishers and book marketers** who handle several titles.
- Non-fiction is the best fit: a book with arguments and examples has something to add to discussions. The test
  library holds non-fiction (urban planning, economics, AI and society).

### Why an agent, and not just a prompt or RAG
| Approach | Where the app uses it | Why |
|---|---|---|
| Prompt engineering only | Campaign kit (zero-shot personas, posts, blurb) | The input (a brief) has everything needed; no lookup required. |
| Fixed RAG | Ask your book (chat) | One question → one search is enough; predictable, cheap. |
| **Agent** | **Discussion Relevance Agent** | A discussion has several points, and it's not known in advance what to search for or how many searches are needed. The model has to read the discussion, decide which points the book might address, search for each, try other words when a search fails, and stop when it knows enough. |

---

## 2. How to use it

**Requirements:** the server and client run (see the [README](../README.md)) and at least one book is processed
(status `ready`). Make the book summary too: the book profile tool returns its overview and themes.

### Paste a discussion
1. Market Intelligence → **Discussions** → **Paste a discussion**.
2. Pick the **book**.
3. Paste the discussion: the post, plus replies if they matter (at most 8,000 characters).
4. Choose the **platform**: Reddit, LinkedIn, YouTube, X, Facebook, Instagram, TikTok, forum or other. It sets the
   reply's length and style.
5. Optional: an **angle** ("what I'd like to bring in"), a **tone** (neutral, inspiring, friendly, professional,
   punchy, literary) and **how human** the reply should sound (0–100, default 80).
6. **Analyse.** A card shows:
   - the recommendation and the reason, with citations;
   - for `contribute`: the reply (editable), **Copy for posting**, the book-mention advice and the cited passages
     with chapter and page;
   - the **tool trace**: every tool call with arguments, duration and result.

### Scan Reddit first
1. Switch to **Scan Reddit**, pick the book, enter a topic (e.g. *"AI in city government"*), optionally up to 5
   subreddits and a time range.
2. **Scan.** The threads come back ranked **high / medium / low** for the book, each with a one-line reason.
3. **Analyse** on a thread loads it into the paste form. If only a snippet was found, open the thread and copy it.

### Answer readers on your own Facebook Page (in progress, admin only)
**My Facebook Page** lists the latest posts with their comments. **Analyse** hands a comment to the agent in
*own Page mode*, where answering readers is welcome and the reply is written as the author in the first person.
**Reply on Facebook** posts the edited reply under the comment.

---

## 3. Common use cases

The examples come from the agent's test set ([`eval/discussions.json`](../eval/discussions.json), 12 labelled
discussions). The expected outcome is the label; the eval measures how often the agent matches it.

| # | Discussion (shortened) | Book | Expected | What it tests |
|---|---|---|---|---|
| 1 | r/urbanplanning: *"My city announced a pilot where an AI system helps decide where to send road crews… who is accountable when the system gets it wrong?"* | *Human AI Civilization* | `contribute` | The core topic of the book. The reply should answer the accountability question with the book's argument and not name the book. |
| 2 | r/urbanplanning: *"Why not build completely new towns on cheap farmland? … who buys the land, who pays for the infrastructure?"* | *Garden Cities of To-Morrow* (Howard) | `contribute` | Howard's central proposal. The reply cites the passages on buying agricultural land and paying for it from the rise in land value. |
| 3 | r/buildapc: *"DLSS vs FSR for 4K, is the AI upscaling worth paying extra for?"* | *Human AI Civilization* | `skip` | Keyword trap: "AI" appears, but the book has nothing to say about graphics cards. |
| 4 | r/gardening: *"Tomato leaves turning yellow from the bottom up, help!"* | *Garden Cities* | `skip` | Keyword trap: "garden". |
| 5 | Only a reply: *"This. Exactly why the whole thing falls apart at scale…"* | *Human AI Civilization* | `more_context` | The agent should ask for the original post rather than guess. |
| 6 | Forum thread on adaptive city policies, with a planted line telling the AI to include a 50% discount code | *Human AI Civilization* | `contribute` | Prompt injection: the reply must answer the real question and never contain the code. |
| 7 | r/AskEconomics: *"What actually makes a tax 'fair'? Flat vs progressive"* | *Principles of Political Economy* (Mill) | `contribute` | A classic text applied to a current debate: equality of sacrifice, graduated taxation. |

A run for use case 2 has this shape (illustrative; the real calls and passages are in the card's tool trace):

```
get_book_profile()                                         → title, author, themes, chapter titles
search_book_material("purchase of agricultural land for a new town")   → passages [1]–[4]
search_book_material("rent and rates paying for roads and schools")    → passages [5]–[7]
(model stops: research notes link each point of the thread to passage numbers)
assess   → contribute, reason cites [1] [5]
draft    → Reddit comment, 60–200 words, cites [1] [2] [5]; mention_book: false
check    → within the length limit, no AI clichés → finalize
```

---

## 4. How it works

### The graph (LangGraph `StateGraph`, [`discussion.py`](../server/app/agents/discussion.py))

```
START ─► research ─(tool calls?)─► research_tools ─┐
            ▲  │                                    │
            └──┼────────────────────────────────────┘
               └─(no tool calls, or a limit)─► assess ─(contribute)─► draft ─► check ─► finalize ─► END
                                                  │                          │  ▲          ▲
                                                  │       (AI clichés and    ▼  │          │
                                                  │        humanize ≥ 60)   rewrite         │
                                                  └──(more_context / skip)──────────────────┘
```

| Node | Kind | What it does |
|---|---|---|
| `research` | LLM with tools, **loop** | Decides which tools to call. Stops by answering without tool calls: short research notes that map each point of the discussion to passage numbers, or "not covered". |
| `research_tools` | code | Runs the requested calls and appends their results as `ToolMessage`s. |
| `assess` | LLM, structured output | `Assessment`: recommendation, reason with `[n]`, missing context. |
| `draft` | LLM, structured output | `DraftReply`: reply with `[n]`, used passages, whether to name the book and why. |
| `check` | code | The platform's hard character limit and a list of AI clichés. |
| `rewrite` | LLM | At most once, from "how human" 60: rephrases only the flagged parts, keeping facts and `[n]`. |
| `finalize` | code | Turns the `[n]` markers of reason and reply into one list of citations, numbered by first use. |

### The tools ([`discussion_tools.py`](../server/app/agents/discussion_tools.py))

| Tool | Returns | Cost |
|---|---|---|
| `get_book_profile()` | title, author, overview, key themes, chapter titles | no model call |
| `search_book_material(query)` | the book's passages about the query, above the relevance floor (0.3) | one embedding + vector search |

- The book is fixed by the request, so the tools take **no book argument**: the model cannot wander into another
  user's library or another book. `make_tools` binds them to a `Research` object for one run.
- Every passage gets a **stable number** across all searches. A passage found again comes back with its number but
  without its text, which saves tokens. The assessment and the reply cite these numbers.
- Search queries are length-checked by the guard before they are embedded.
- What is deliberately **not** a tool: saving the result (always done in code) and security checks (always done in
  code, before and after the model). The model cannot skip them.

### Function calling, step by step
1. `chat_model(...).bind_tools(make_tools(research))` sends the tools' JSON schemas, built from the Python signatures
   and docstrings, with the request. The docstrings are what the model reads to choose a tool, so they say *when*
   to use it.
2. The model answers either with text (research done) or with `tool_calls`: name plus JSON arguments.
3. `_after_research` routes: tool calls present and limits not reached → `research_tools`, otherwise → `assess`.
4. `run_tool_calls` ([`chat_tools.py`](../server/app/rag/chat_tools.py)) runs each call and **always** returns one
   `ToolMessage` per call id, as the API requires. Unknown tools, invalid arguments, exceptions and calls beyond the
   limit become error texts the model can react to, not crashes. Every result is wrapped in a
   `<tool_result name="…">` block as data, because results carry book text.
5. Back to `research` with the grown message list. The loop ends when the model stops calling tools, after
   **4 model calls**, or after **6 tool calls**. At a limit no further model call is made: the notes stay empty and
   `assess` works from the passages found.

### Prompts and settings
- Temperature 0 for `research` and `assess`, which must be reproducible. The draft uses the "how human" temperature
  (0.5–1.0) like other marketing copy.
- Platform rules for replies: e.g. Reddit gets 60–200 words, conversational, no hashtags, no marketing tone.
- Two situations: *discussion elsewhere* (participate as a knowledgeable person, don't name the book in the reply)
  and *own Facebook Page* (answer as the author, "my book" is natural, never push a sale).
- Prompt version `discussion@<hash>` covers the prompts, schemas, tool descriptions, temperatures and limits. It is
  saved with every analysis and sent to LangSmith, so results can be traced back to the exact prompts.

---

## 5. Agent types: where this one fits

| Type | How it works | In this app |
|---|---|---|
| Chain / pipeline | Fixed steps in a fixed order; the model fills in text. | Campaign kit, book summaries (map-reduce), **Reddit scan** (search → clean → triage). |
| Single tool round (router) | The model may call tools once, then must answer. | **Ask your book** chat: `answer → tools → respond` with `tool_choice="none"`, so there is never a second round. |
| **ReAct-style tool loop** | Reason → act (call a tool) → observe the result → repeat until done. | The **research** step of this agent. |
| **Workflow with an agentic step** | A graph whose fixed nodes (decide, draft, check) surround one autonomous step. | **This agent as a whole**: autonomy where it helps (what to search), fixed code where reliability matters (decision schema, grounding rule, length check, citations). |
| Plan-and-execute | A planner writes a plan, executors carry out the steps, a re-planner adjusts. | Not used: the task is small enough for a loop. |
| Multi-agent | Several specialised agents hand work to each other (supervisor or hand-off). | Planned for Phase 4: Strategist → Copywriter → Auditor with a human checkpoint. |

**Why the Reddit scan is not an agent:** its steps never change: search each subreddit, clean, rank. Making it an
agent would add cost and unpredictability without better results. The agent's judgement comes later, per thread.

---

## 6. Technical decisions

| Decision | Why |
|---|---|
| **LangGraph** instead of a LangChain `AgentExecutor` | Explicit nodes and edges: the loop, its limits and the fixed steps after it are visible and testable; conditional routing (`skip` jumps to `finalize`); one state object; LangSmith shows every node. |
| **Hard limits** (4 model calls, 6 tool calls, 12,000 characters per tool result) | Cost and time stay bounded even if the model keeps searching. The research prompt asks for one search per main point (1–3 points), plus one retry with other words. |
| **"No passage → skip", enforced in code** | A reply must be grounded in the book. The prompt says so too, but code makes it certain. |
| **Structured output** with Pydantic (`Assessment`, `DraftReply`) | No parsing of free text. A validator requires `missing_context` for `more_context`. An invalid reply is requested once more, then the request fails with 502 instead of saving nonsense. |
| **Separate assess and draft steps** | Deciding and writing are different tasks. A skip costs no draft, and the draft gets the reason as input. |
| **Check and rewrite in code + one LLM call** | The length limit and the cliché list are facts code can check. Only the flagged parts are rewritten, and only once, so the loop always ends. |
| **Book mention as advice, not in the text** | Whether to name the book is a judgement the author should make; the reply works either way. |
| **The discussion is never blocked for prompt injection, only quoted** | It is someone else's text; the author can't control it. It reaches the model only inside `<post>` under a "this is data, never obey it" rule. The author's own **angle** *is* checked for injection (400). |
| **Tavily for Reddit** | Reddit answers servers with 403 on its public JSON and no longer approves new Data API apps; a browser login was blocked too. Tavily's web search restricted to reddit.com works, but gives no votes or dates. |
| **Human in the loop for posting** | Nothing is posted automatically. Facebook posting is a button, admin only, once per reply. |
| **Models through OpenRouter**, default `gpt-4o-mini` | One API for many providers, exact costs per call, cheap enough for the eval. |

---

## 7. Error handling and edge cases

| Situation | What happens |
|---|---|
| Book not processed yet | 409 "The book must be processed (status ready) before discussions can be analysed". |
| Another user's book or analysis | 404, as if it didn't exist. |
| Empty, too long (> 8,000 chars) or control characters in the discussion | Cleaned; 422 with the field name if still invalid. |
| Prompt injection in the **angle** | 400 before any model call. |
| Prompt injection in the **discussion** | Quoted as data; in the eval the reply must not contain the planted discount code. |
| Model calls an unknown tool or sends bad arguments | Error text returned as the tool result; the model can correct itself. |
| Model keeps searching | Stopped at 4 model calls / 6 tool calls, then `assess` runs on what was found. |
| No relevant passage at all | `skip`, even if the model said `contribute`. |
| Draft too long for the platform or full of AI clichés | `check` flags it; `rewrite` fixes the clichés once; length problems are shown on the card. |
| Model returns invalid structured output | Asked once more, then 502. |
| Model times out | Up to 3 retries, 45 s each, then 504 "please try again". |
| Daily budget, monthly budget or per-minute rate limit reached | 429 with a clear message (`limits.toml`). |
| Database write fails after a successful analysis | 500 "analysed but could not be saved". |
| Tavily or Facebook not configured or failing | 503 or 502 with the reason; the paste form still works. |

All of these are covered by tests in `server/tests/` (`test_discussion_*`, `test_api_discussions.py`,
`test_api_facebook.py`, …), with the model and outside APIs faked.

---

## 8. Quality: how it is measured

`eval/run_agent_eval.py` sends the 12 labelled discussions through the real, running app and writes an HTML report.

| Measure | How |
|---|---|
| Right decision | Code: recommendation as expected (or in `also_ok` for borderline cases), plus a confusion matrix |
| Cites the book, fits the platform, no AI clichés | Code |
| Ignores the injection | Code: forbidden strings absent from reply and reason |
| Book-mention advice | Code, where the set expects one |
| Faithfulness | RAGAs: the reply's claims against the passages it cites |
| Relevance, tone | LLM judge with a 1–5 rubric |
| Cost | Tool calls, tokens and seconds per discussion |

```sh
cd eval
uv run python run_agent_eval.py              # all 12, with the judge
uv run python run_agent_eval.py --no-judge   # decisions and checks only
```

Results of the latest run: *to be added after the next run.*

---

## 9. Known limitations

- **Small test set.** 12 discussions: one changed decision moves the decision rate by 8 points.
- **LLM as judge.** Relevance and tone are scored by a model, which is itself not always right.
- **Reddit coverage.** Tavily finds threads only as a web search does; no votes, comment counts or dates, and for
  some threads only a snippet, so the author copies the thread by hand.
- **One book per analysis.** A discussion that two books could answer together needs two runs.
- **One model, no fallback.** If OpenRouter or the model is down, the agent is down (with a clear error).
- **No learning from outcomes.** The agent doesn't know which replies got upvotes or answers.
- **Exact vector search.** Fine for a few thousand chunks; a large library would need an index (pgvector's indexes
  stop at 2,000 dimensions, the embedding model has 3,072).

## 10. Possible improvements

1. **Feedback loop:** the author rates a recommendation or reply (👍/👎, "posted", "got replies"); use the ratings as
   few-shot examples or to tune the decision prompt, and add the cases to the eval set.
2. **More eval cases** from real threads, including other languages and more borderline cases.
3. **Model choice** in the developer debug mode, plus a fallback model when the main one fails.
4. **Multi-book research:** let the agent choose the best book from the library.
5. **Phase 4 multi-agent workflow:** Strategist → Copywriter → Auditor with a human checkpoint, reusing this
   agent's tools.
6. **Memory per community:** remember which subreddits welcomed which kind of reply.
