# RAG evaluation (RAGAs)

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
environment or `server/.env`.

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

## Why a separate project

RAGAs 0.4 needs older versions of `langchain-community` and of the OpenAI SDK than the app uses. Its own
environment here keeps the app's dependencies unchanged; the evaluation talks to the app only over HTTP.

## Known limits

- The judge is itself a language model, so scores vary a little between runs, and it can be wrong: e.g.
  answer relevancy gives 0 to a correct answer that contains a hedge ("depends on the circumstances"),
  because RAGAs treats it as noncommittal.
- The reference answers were written with the help of the app's own search, so context recall tends to be
  high; questions whose answer the search does not find would test retrieval harder.
- OpenRouter returns one generation per call, so answer relevancy uses `strictness=1` (RAGAs' default is 3).
