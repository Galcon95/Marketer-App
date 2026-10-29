"""RAG evaluation of the marketer app with RAGAs, run against the app's real API.

    testset.json ──► POST /ask (the running app: condense → retrieve → answer, like the chat) ──► answer + passages
                 ──► RAGAs (judge model via OpenRouter) ──► faithfulness, answer relevancy,
                                                            context precision, context recall per question
                 ──► reports/<run id>/results.json, results.csv, report.html (+ summary in the terminal)

Usage (from eval/, with the API running on http://127.0.0.1:8000):
    uv run python run_eval.py                      # all questions, k=6
    uv run python run_eval.py --k 10 --label "k=10" # compare a setting; the report shows all runs side by side
    uv run python run_eval.py --limit 3            # quick check with the first 3 questions

A separate project (own environment) because RAGAs needs older library versions than the app. Each
question becomes a chat on the server; the script deletes it again right after reading the answer. It
waits when the app's rate limit answers 429. Needs OPENROUTER_API_KEY (environment variable or server/.env).

Each run records the app's prompt version (from the answers, e.g. "qa@5c14fd46", see server/app/core/prompts.py)
and the git commit (with "-dirty" if tracked files were changed), so the report can tie score changes to
prompt or code changes instead of relying on --label alone.
"""

import argparse
import csv
import json
import math
import os
import subprocess
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import httpx

from report import METRICS, build_report

EVAL_DIR = Path(__file__).resolve().parent
REPORTS_DIR = EVAL_DIR / "reports"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def main() -> None:
    """One evaluation run: ask the app every test question, score the answers with RAGAs, then write
    results.json, results.csv and report.html to reports/<run id>/ and print a summary."""
    args = _parse_args()
    _load_server_env()
    if not os.getenv("OPENROUTER_API_KEY"):
        sys.exit("OPENROUTER_API_KEY is not set (environment variable or server/.env).")
    items = json.loads((EVAL_DIR / "testset.json").read_text(encoding="utf-8"))[: args.limit or None]

    print(f"Asking the app {len(items)} questions (k={args.k}) ...")
    rows, app_model, prompt_versions = [], "", set()
    with httpx.Client(base_url=args.api, timeout=300) as api:
        for i, item in enumerate(items, start=1):
            result = _ask(api, args.project, item["question"], args.k)
            app_model = result["model"]
            prompt_versions.add(result.get("prompt_version") or "unversioned")
            rows.append({
                "id": item["id"], "book": item["book"], "question": item["question"], "reference": item["reference"],
                "answer": result["answer"], "contexts": [h["chunk"]["text"] for h in result["passages"]],
                "citations": len(result["citations"]), "tokens": result["tokens"],
                "tool_calls": [t["name"] for t in result.get("tool_calls", [])], "scores": {},
            })
            print(f"  {i:>2}/{len(items)} {item['id']}: {len(result['citations'])} citations, {result['tokens']:,} tokens")

    print(f"Scoring with RAGAs (judge {args.judge}, {args.workers} calls in parallel) ...")
    scores, judge_tokens = _score(rows, args.judge, args.workers)
    for row, row_scores in zip(rows, scores):
        row["scores"] = row_scores

    run_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run = {
        "run_id": run_id,
        "config": {"k": args.k, "label": args.label, "app_model": app_model, "judge_model": args.judge,
                   "prompt_version": ", ".join(sorted(prompt_versions)), "git_commit": _git_commit(),
                   "questions": len(rows), "api": args.api, "workers": args.workers},
        "averages": {key: _mean(r["scores"].get(key) for r in rows) for key, _, _ in METRICS},
        # How many questions got a score per metric; below "questions", the average rests on fewer questions.
        "scored": {key: sum(r["scores"].get(key) is not None for r in rows) for key, _, _ in METRICS},
        "tokens": {"app": sum(r["tokens"] for r in rows), "judge": judge_tokens},
        "rows": rows,
    }
    out = REPORTS_DIR / run_id
    out.mkdir(parents=True)
    (out / "results.json").write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_csv(out / "results.csv", rows)
    history = _history()
    (out / "report.html").write_text(build_report(run, history), encoding="utf-8")
    _print_summary(run, out / "report.html")


def _parse_args() -> argparse.Namespace:
    """The command line options (see --help): API address, project, k, question limit, label, judge model, workers."""
    p = argparse.ArgumentParser(description="RAG evaluation of the marketer app with RAGAs")
    p.add_argument("--api", default="http://127.0.0.1:8000", help="base URL of the running app API")
    p.add_argument("--project", default="demo-campaign", help="project (client) whose books are asked")
    p.add_argument("--k", type=int, default=6, help="passages retrieved per question (the app's default is 6)")
    p.add_argument("--limit", type=int, default=0, help="only the first N questions (0 = all)")
    p.add_argument("--label", default="", help="a note for this run, e.g. 'hybrid search', shown in the report")
    p.add_argument("--judge", default="openai/gpt-4o-mini", help="OpenRouter model that judges the answers")
    p.add_argument("--workers", type=int, default=4,
                   help="judge calls in parallel (RAGAs' default of 16 runs into OpenRouter timeouts)")
    return p.parse_args()


def _load_server_env() -> None:
    """Read server/.env (KEY=VALUE lines) for variables not already set, like the app does."""
    env = EVAL_DIR.parent / "server" / ".env"
    if not env.is_file():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and not key.startswith("#") and value and not os.getenv(key.strip()):
            os.environ[key.strip()] = value.strip()


def _ask(api: httpx.Client, project: str, question: str, k: int) -> dict:
    """Ask the app one question (a new chat each time, deleted again afterwards); waits on 429, up to 5 times."""
    for _ in range(5):
        response = api.post(f"/projects/{project}/ask", json={"question": question, "k": k})
        if response.status_code == 429:
            wait = int(response.headers.get("Retry-After", "10"))
            print(f"     rate limit reached, waiting {wait} s ...")
            time.sleep(wait)
            continue
        response.raise_for_status()
        result = response.json()
        if result.get("conversation_id"):
            api.delete(f"/conversations/{result['conversation_id']}")
        return result
    sys.exit("The app kept answering 429 (rate limit); try again later.")


def _score(rows: list[dict], judge_model: str, workers: int) -> tuple[list[dict], int]:
    """RAGAs scores per row (keys as in report.METRICS; None where a metric failed) and the judge's tokens.

    At most `workers` judge calls run at once, each may take up to 5 minutes and is retried on errors.
    """
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    from langchain_core.callbacks import UsageMetadataCallbackHandler
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas import EvaluationDataset, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import Faithfulness, LLMContextPrecisionWithReference, LLMContextRecall, ResponseRelevancy
    from ragas.run_config import RunConfig

    usage = UsageMetadataCallbackHandler()
    key = os.environ["OPENROUTER_API_KEY"]
    llm = ChatOpenAI(model=judge_model, base_url=OPENROUTER_BASE_URL, api_key=key, temperature=0, callbacks=[usage])
    embeddings = OpenAIEmbeddings(model="openai/text-embedding-3-small", base_url=OPENROUTER_BASE_URL, api_key=key,
                                  check_embedding_ctx_length=False)
    dataset = EvaluationDataset.from_list([
        {"user_input": r["question"], "retrieved_contexts": r["contexts"], "response": r["answer"], "reference": r["reference"]}
        for r in rows
    ])
    metrics = {  # RAGAs column → our key
        "faithfulness": ("faithfulness", Faithfulness()),
        # strictness=1: OpenRouter returns one generation per call (no "n"), so RAGAs' default of 3 isn't possible.
        "answer_relevancy": ("answer_relevancy", ResponseRelevancy(strictness=1)),
        "llm_context_precision_with_reference": ("context_precision", LLMContextPrecisionWithReference()),
        "context_recall": ("context_recall", LLMContextRecall()),
    }
    result = evaluate(dataset, metrics=[m for _, m in metrics.values()], llm=LangchainLLMWrapper(llm),
                      embeddings=LangchainEmbeddingsWrapper(embeddings), show_progress=True,
                      run_config=RunConfig(max_workers=workers, timeout=300, max_retries=10, max_wait=60))
    table = result.to_pandas()
    scores = [{ours: _number(record.get(column)) for column, (ours, _) in metrics.items()}
              for record in table.to_dict(orient="records")]
    judge_tokens = sum(u.get("total_tokens", 0) for u in usage.usage_metadata.values())
    return scores, judge_tokens


def _number(value) -> float | None:
    """A score as float, None if missing or NaN."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) else round(value, 4)


def _mean(values) -> float | None:
    """Average of the scores that exist, None if none does."""
    present = [v for v in values if v is not None]
    return round(sum(present) / len(present), 4) if present else None


def _write_csv(path: Path, rows: list[dict]) -> None:
    """One line per question with its scores, answer and reference (for Excel and the like)."""
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "book", "question", *[key for key, _, _ in METRICS], "citations", "tokens", "answer", "reference"])
        for r in rows:
            writer.writerow([r["id"], r["book"], r["question"], *[r["scores"].get(key) for key, _, _ in METRICS],
                             r["citations"], r["tokens"], r["answer"], r["reference"]])


def _git_commit() -> str:
    """Short hash of the checked-out commit, "-dirty" appended if tracked files differ from it; "" without git."""
    def git(*command: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *command], cwd=EVAL_DIR, capture_output=True, text=True)
    try:
        head = git("rev-parse", "--short", "HEAD")
        if head.returncode != 0:
            return ""
        return head.stdout.strip() + ("-dirty" if git("diff", "--quiet", "HEAD").returncode else "")
    except OSError:  # git not installed
        return ""


def _history() -> list[dict]:
    """All runs so far (results.json in reports/), oldest first."""
    runs = []
    for path in sorted(REPORTS_DIR.glob("*/results.json")):
        try:
            runs.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            print(f"  skipping unreadable {path}")
    return runs


def _print_summary(run: dict, report: Path) -> None:
    """The averages as bars in the terminal, plus where the report is."""
    cfg = run["config"]
    print(f"\nRAG evaluation · {cfg['questions']} questions · k={cfg['k']} · {cfg['app_model']}"
          + f" · prompts {cfg['prompt_version']} · commit {cfg['git_commit'] or 'unknown'}"
          + (f" · {cfg['label']}" if cfg["label"] else ""))
    for key, label, _ in METRICS:
        v, scored = run["averages"].get(key), run["scored"][key]
        bar = "n/a" if v is None else "█" * round(v * 22) + "░" * (22 - round(v * 22))
        gap = f"  ⚠ only {scored}/{cfg['questions']} scored" if scored < cfg["questions"] else ""
        print(f"  {label:<18} {'n/a ' if v is None else f'{v:.2f}'}  {bar}{gap}")
    if any(n < cfg["questions"] for n in run["scored"].values()):
        print("  Some scores are missing (judge errors or timeouts): those averages rest on fewer questions\n"
              "  and are not fully comparable with other runs. Try again, or with fewer --workers.")
    print(f"  tokens: app {run['tokens']['app']:,} · judge {run['tokens']['judge']:,}")
    print(f"  report: {report}")


if __name__ == "__main__":
    main()
