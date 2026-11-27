"""Evaluation of Ask the app (server/app/rag/manual_qa.py) on help_questions.json.

Each question goes to the real model, the same call as POST /help/ask (no running server and no sign-in needed: the
script imports the server's code). Every answer is checked by rules, not by a judge model, so a run costs only the
questions themselves (16 × about 7,000 tokens, about one cent with gpt-4o-mini):

    covered     the model says correctly whether the manual covers the question (true for how-to questions, false
                for things the manual does not describe or that are not about the app)
    section     the answer is based on one of the expected sections (its "Read more" links or a link in the text);
                the chapter (## heading) that contains an expected subsection (###) counts too, since its link lands
                the user in the right place (decided after run 2, where a correct answer linked the chapter)
    mentions    the answer names the buttons, tabs or values a user needs (as the manual writes them)
    language    the answer is in the language of the question (a German question gets German)
    clean       no link other than to the manual's sections survived (the code removes them; this checks it)

An item passes when all its checks pass. The table shows each item, the totals per check and per kind of question;
reports/help/<date_time>/results.json keeps everything with the prompt version and the git commit, to compare runs
after a change of the manual or the prompt. server/tests/test_help.py checks that every expected section exists, so
renaming a heading cannot silently break this set.

    cd server
    uv run python ../eval/run_help_eval.py              # all questions
    uv run python ../eval/run_help_eval.py --only de    # items whose id contains "de"
    uv run python ../eval/run_help_eval.py --no-save
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
SERVER_DIR = EVAL_DIR.parent / "server"
SET_FILE = EVAL_DIR / "help_questions.json"
CHECKS = ("covered", "section", "mentions", "language", "clean")
GERMAN = re.compile(r"\b(und|die|der|das|du|Sie|deine?|klicke?|öffne|mit|auf)\b")
LINK = re.compile(r"\]\(([^)]+)\)|https?://|www\.")


def load_items(path: Path = SET_FILE) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["items"]


def chapters(manual_sections: list[tuple[int, str, str]]) -> dict[str, str]:
    """Each subsection's anchor → the anchor of the chapter (## heading) it is in."""
    parent, found = "", {}
    for level, _, anchor in manual_sections:
        if level == 2:
            parent = anchor
        else:
            found[anchor] = parent
    return found


def check(item: dict, answer: str, covered: bool, sections: list[str],
          parents: dict[str, str] | None = None) -> dict[str, bool]:
    """The rule checks of one answer (see the module docstring); `parents` from chapters()."""
    linked = {m.group(1).split("#", 1)[-1] for m in re.finditer(r"\]\((/help#[^)]+)\)", answer)}
    used = set(sections) | linked
    expected = set(item["sections"]) | {(parents or {}).get(s, s) for s in item["sections"]}
    text = answer.lower()
    german = len(GERMAN.findall(answer)) >= 3
    others = [m.group(0) for m in LINK.finditer(answer) if not (m.group(1) or "").startswith("/help")]
    return {
        "covered": covered == item["covered"],
        "section": not item["sections"] or bool(used & expected),
        "mentions": all(word.lower() in text for word in item["must_mention"]),
        "language": german if item["language"] == "de" else not german,
        "clean": not others,
    }


def summarize(results: list[dict]) -> dict:
    """Pass counts overall, per check and per kind of question."""
    kinds: dict[str, list[int]] = {}
    for r in results:
        passed, total = kinds.setdefault(r["kind"], [0, 0])
        kinds[r["kind"]] = [passed + r["passed"], total + 1]
    return {
        "passed": sum(r["passed"] for r in results), "total": len(results),
        "checks": {c: sum(r["checks"][c] for r in results) for c in CHECKS},
        "kinds": {k: {"passed": p, "total": t} for k, (p, t) in kinds.items()},
        "tokens": sum(r["tokens"] for r in results),
    }


def git_commit() -> str:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                cwd=EVAL_DIR, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True,
                               text=True, cwd=EVAL_DIR, check=True).stdout.strip()
        return commit + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--only", default="", help="only items whose id contains this")
    parser.add_argument("--no-save", action="store_true", help="print the table only")
    args = parser.parse_args()

    os.environ.setdefault("TELEGRAM_POLLING", "false")
    sys.path.insert(0, str(SERVER_DIR))
    from app.core import manual  # noqa: E402  (the server's code, after sys.path)
    from app.rag import manual_qa  # noqa: E402

    parents = chapters(manual.sections())
    items = [i for i in load_items() if args.only in i["id"]]
    results = []
    for item in items:
        reply = manual_qa.ask_app(item["question"], item["page"])
        sections = [s.anchor for s in reply.sections]
        checks = check(item, reply.answer, reply.covered, sections, parents)
        results.append({**item, "answer": reply.answer, "answer_covered": reply.covered, "answer_sections": sections,
                        "tokens": reply.tokens, "checks": checks, "passed": all(checks.values())})
        failed = [c for c, ok in checks.items() if not ok]
        print(f"{'PASS' if not failed else 'FAIL'}  {item['id']:<14} {item['kind']:<12} "
              + (f"failed: {', '.join(failed)}" if failed else ""))

    summary = summarize(results)
    print(f"\n{summary['passed']}/{summary['total']} items passed · "
          + " · ".join(f"{c} {n}/{summary['total']}" for c, n in summary["checks"].items())
          + f" · {summary['tokens']:,} tokens · prompt {manual_qa.PROMPT_VERSION}")
    for kind, k in summary["kinds"].items():
        print(f"  {kind:<12} {k['passed']}/{k['total']}")
    for r in results:
        if not r["passed"]:
            print(f"\n--- {r['id']}: {r['question']}\n{r['answer']}\nsections: {r['answer_sections']}")

    if not args.no_save:
        out = EVAL_DIR / "reports" / "help" / datetime.now().strftime("%Y-%m-%d_%H%M%S")
        out.mkdir(parents=True, exist_ok=True)
        (out / "results.json").write_text(json.dumps({
            "prompt_version": manual_qa.PROMPT_VERSION, "commit": git_commit(), "summary": summary,
            "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nSaved: {out / 'results.json'}")


if __name__ == "__main__":
    main()
