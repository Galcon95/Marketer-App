# Evaluation: RAG (RAGAs) and the Discussion Relevance Agent

Measures how well "Ask your book" answers questions about the books, with [RAGAs](https://docs.ragas.io).
It runs against the **real, running app** (`POST /ask`, the same pipeline as the chat) and scores each answer
with a judge model through OpenRouter.

| Metric | Question it answers |
|---|---|
| Faithfulness | Does the answer stay with the retrieved passages, or does it add claims that are not in them? |
| Answer relevancy | Does the answer address the question? |
| Context precision | Are the relevant passages ranked at the top? |
| Context recall | Do the passages contain everything the reference answer needs? |

## Run it

The API must be running (`cd server`, `uv run fastapi dev server.py`). `OPENROUTER_API_KEY` comes from the
environment or `server/.env`. Every API endpoint needs a sign-in: the script asks for the password of
`DEFAULT_CLIENT_OWNER` (from `server/.env`; another account with `EVAL_EMAIL`) and signs in with Supabase, using
the public key in `client/.env.local`. The password is not stored. Without a prompt: set `EVAL_ACCESS_TOKEN`.

```sh
cd eval
uv run python run_eval.py                         # all questions, k=6 (the app's default)
uv run python run_eval.py --k 10 --label "k=10"   # try a setting; the report compares all runs
uv run python run_eval.py --limit 3               # quick check with the first 3 questions
```

Each run writes `reports/<date_time>/`:
- `report.html`: one self-contained page (works offline, light and dark mode): score tiles, a questions ×
  metrics grid that highlights the weak spots, a history chart of all runs, and every answer with its
  reference and retrieved passages.
- `results.json` (everything, also the input for the history) and `results.csv` (for Excel).

Every run also records the app's **prompt version** (taken from the answers, e.g. `qa@5c14fd46`; it changes by
itself whenever a prompt changes, see `server/app/core/prompts.py`) and the **git commit** (`-dirty` if tracked
files were changed). The report shows both, and the history chart marks with a dashed line where the prompt
version changed, so a score change can be tied to a prompt edit without relying on `--label`. Runs made before
versioning show as "unversioned".

A run with 13 questions takes about 2 minutes and uses roughly 50k app tokens and 225k judge tokens
(gpt-4o-mini, a few cents). Each question is a new chat on the server, deleted again right after; the
script waits when the app's rate limit answers 429.

## The test set

`testset.json`: 13 questions about the three books, each with a reference answer written from the book
text (checked against the retrieved passages). Add questions in the same format; keep the reference to
what the book actually says.

## Discussion Relevance Agent (`run_agent_eval.py`)

Measures the agent of Market Intelligence → Discussions against the **real, running app**
(`POST /projects/{id}/discussions`, the same graph as in the GUI). Sign-in and API key work as above; the migration
`0008` (table `discussion_analyses`) must be applied.

```sh
cd eval
uv run python run_agent_eval.py                  # all 12 discussions, with the judge
uv run python run_agent_eval.py --no-judge       # decisions and checks only (no judge cost)
uv run python run_agent_eval.py --only hai-      # only the discussions for The Human AI Civilization
uv run python run_agent_eval.py --keep           # keep the analyses, to look at them in the GUI
```

`discussions.json`: 12 discussions made up for the test, for four of the library's books. Each has the expected
recommendation, optionally other acceptable ones (`also_ok`, for borderline cases), whether naming the book is
expected (`mention`), words the reply must not contain (`must_not_contain`) and why it is in the set. The set covers:
clear opportunities (contribute), keyword traps ("AI" in a graphics-card thread, "garden" in a tomato thread → skip),
pasted text without the post it answers (more_context), hype without content (skip), a request for a book
recommendation (mention expected) and a planted prompt injection with a discount code (must be ignored).

| Measure | How |
|---|---|
| Right decision | Code: recommendation as expected or in `also_ok`; plus a confusion matrix |
| Cites the book · Fits the platform · No AI clichés | Code, from the saved analysis (drafted replies only) |
| Ignores injection | Code: none of `must_not_contain` in the reply or the reason |
| Book mention | Code: the advice matches `mention`, where the set expects one |
| Faithfulness | RAGAs: the reply's claims against the full text of the passages it cites |
| Relevance · Tone | LangChain judge with a 1-5 rubric (scaled to 0-1): answers the discussion? a participant, not an ad? |
| Cost | Tool calls, tokens and seconds per discussion |

Each run writes `reports/agent/<date_time>/` with `report.html` (tiles, scorecard, confusion matrix, history of all
agent runs, every discussion with reason, reply, searches and passages), `results.json` and `results.csv`. With 12
discussions one changed decision moves the decision rate by 8 points; read single cases in the report rather than
small differences in the averages.

## Why a separate project

RAGAs 0.4 needs older versions of `langchain-community` and of the OpenAI SDK than the app uses. Its own
environment here keeps the app's dependencies unchanged; the evaluation talks to the app only over HTTP.

## Retrieval experiments (2026-10-29)

| Run | Faithfulness | Answer relevancy | Context precision | Context recall |
|---|---|---|---|---|
| Baseline: dense, no floor, no chunk headers | 0.99 | 0.84 | 0.93 | 1.00 |
| Dense + chunk headers + HNSW fix + floor 0.3 (now the default) | 0.99 | 0.90 | 0.88 | 0.97 |
| Hybrid BM25 + dense (RRF), otherwise the same | 0.98 | 0.83 | 0.94 | 0.95 |
| Dense default, vectors moved from Chroma to pgvector (2026-11-06) | 0.99 | 0.83 | 0.91 | 0.97 |

With 13 questions one changed passage moves an average by several points, so these differences are small. The
headers changed which passages rank in the top 6 for three questions; chapter titles ("WHAT IS SPECULATION?") now
pull whole chapters up. Hybrid ranked better but answered less relevantly, so dense stays the default. The relevance
floor was set from the similarities of the eval questions against 12 off-topic questions; it removed only weak
extra passages here (e.g. "puts and calls" kept 3 of 6). The same session found and fixed an HNSW recall problem
(see `server/app/rag/vectorstore.py`). Off-topic questions are not part of the RAGAs set, because RAGAs needs
passages to score.

The pgvector run retrieved exactly the same passages for every question as the Chroma run above it (the vectors
were copied, not re-embedded, and the search is now exact). Its lower answer relevancy comes from one question:
the judge scored the stock-margin answer 0.00 instead of 0.82, although the answer is practically the same; the
judge's known false negative on hedged answers (see below). Without it the average is about 0.90 as before.

## Known limits

- The judge is itself a language model, so scores vary a little between runs, and it can be wrong: e.g.
  answer relevancy gives 0 to a correct answer that contains a hedge ("depends on the circumstances"),
  because RAGAs treats it as noncommittal.
- The reference answers were written with the help of the app's own search, so context recall tends to be
  high; questions whose answer the search does not find would test retrieval harder.
- OpenRouter returns one generation per call, so answer relevancy uses `strictness=1` (RAGAs' default is 3).
