"""Red-team evaluation of the injection guard (server/app/core/guard.py check_prompt_injection).

Runs every text of guard_redteam.json through the guard and measures:
    catch rate         share of the attacks with risk "high" (blocked for the user's own text, flagged for others')
    false-alarm rate   share of the ordinary texts with risk "high"
per category, and lists every miss and every false alarm. The set has two parts: "dev", on which the rules were
tuned, and "holdout", written afterwards and never used to change a rule: its numbers are the honest ones. No model calls, no running server, no cost: the guard is
pure code. Run it with the server's packages:

    cd server
    uv run python ../eval/run_guard_eval.py            # table + reports/guard/<date_time>/results.json
    uv run python ../eval/run_guard_eval.py --no-save  # table only

server/tests/test_guard_redteam.py runs the same set as a test, so a change of the rules that catches less or
alarms more fails there.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
SERVER_DIR = EVAL_DIR.parent / "server"
SET_FILE = EVAL_DIR / "guard_redteam.json"


def load_items(path: Path = SET_FILE) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["items"]


SPLITS = ("dev", "holdout")


def evaluate(items: list[dict], check) -> dict:
    """Run `check` (guard.check_prompt_injection) over the items.

    Returns:
        {"dev": {"attacks": {...}, "benign": {...}}, "holdout": {...}, "rows": [...]}: per part of the set and kind
        the total, the number flagged high, the rate and the same per category; one row per item with the risk and
        the rules that matched.
    """
    rows = []
    for item in items:
        report = check(item["text"])
        rows.append({**item, "risk": report.risk, "rules": [f.rule for f in report.findings],
                     "correct": (report.risk == "high") == (item["kind"] == "attack")})

    def summary(split: str, kind: str) -> dict:
        chosen = [r for r in rows if r["kind"] == kind and r.get("split", "dev") == split]
        categories = {}
        for row in chosen:
            c = categories.setdefault(row["category"], {"total": 0, "high": 0})
            c["total"] += 1
            c["high"] += row["risk"] == "high"
        for c in categories.values():
            c["rate"] = round(c["high"] / c["total"], 3)
        high = sum(r["risk"] == "high" for r in chosen)
        return {"total": len(chosen), "high": high, "rate": round(high / len(chosen), 3) if chosen else 0.0,
                "categories": categories}

    return {**{split: {"attacks": summary(split, "attack"), "benign": summary(split, "benign")} for split in SPLITS},
            "rows": rows}


TITLES = {"dev": "DEV (the rules were tuned on these texts)",
          "holdout": "HOLDOUT (written afterwards, never used to change a rule)"}


def table(result: dict) -> str:
    lines = []
    for split in SPLITS:
        lines += [TITLES[split], "=" * len(TITLES[split])]
        for title, key, word in (("Attacks: caught (risk high)", "attacks", "caught"),
                                 ("Ordinary texts: false alarms (risk high)", "benign", "alarms")):
            part = result[split][key]
            lines += [title, f"  {'category':<16}{word:>8}{'of':>5}{'rate':>8}"]
            for name, c in part["categories"].items():
                lines.append(f"  {name:<16}{c['high']:>8}{c['total']:>5}{c['rate']:>8.0%}")
            lines += [f"  {'all':<16}{part['high']:>8}{part['total']:>5}{part['rate']:>8.0%}", ""]
    missed = [r for r in result["rows"] if r["kind"] == "attack" and not r["correct"]]
    alarms = [r for r in result["rows"] if r["kind"] == "benign" and not r["correct"]]
    for title, chosen in (("Missed attacks", missed), ("False alarms", alarms)):
        lines.append(f"{title} ({len(chosen)}):")
        for r in chosen:
            text = " ".join(r["text"].split())
            rules = f" [{', '.join(r['rules'])}]" if r["rules"] else ""
            lines.append(f"  {r['id']:<20}{text[:90]}{'…' if len(text) > 90 else ''}{rules}")
        lines.append("")
    return "\n".join(lines)


def _git_commit() -> str:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=EVAL_DIR, capture_output=True,
                                text=True, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=EVAL_DIR,
                               capture_output=True, text=True, timeout=10).stdout.strip()
        return commit + ("-dirty" if commit and dirty else "")
    except (OSError, subprocess.SubprocessError):
        return ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--no-save", action="store_true", help="print the table only, write no report")
    parser.add_argument("--label", default="", help="a note for this run, saved in results.json")
    args = parser.parse_args()

    sys.path.insert(0, str(SERVER_DIR))
    from app.core import guard  # the server's own module (run with the server's packages, see above)

    result = evaluate(load_items(), guard.check_prompt_injection)
    sys.stdout.reconfigure(encoding="utf-8")  # the texts have other alphabets; a Windows console may not
    print(table(result))
    if not args.no_save:
        now = datetime.now()
        folder = EVAL_DIR / "reports" / "guard" / now.strftime("%Y-%m-%d_%H%M%S")
        folder.mkdir(parents=True)
        (folder / "results.json").write_text(json.dumps(
            {"run_at": now.isoformat(timespec="seconds"), "label": args.label, "git_commit": _git_commit(),
             **result}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Saved {folder / 'results.json'}")


if __name__ == "__main__":
    main()
