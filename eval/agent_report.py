"""Self-contained HTML report of one agent evaluation run (run_agent_eval.py), in the style of the RAG report
(report.py: same colors, light and dark mode, tooltips).

    tiles      the headline rates and judge scores of this run
    scorecard  discussions × checks, one cell per value (weak spots stand out), hover for details
    confusion  expected recommendation × the agent's recommendation
    history    the headline numbers of all agent runs so far, as a table
    details    per discussion: why it is in the set, the agent's reason, reply, searches and cited passages
"""

import html

from report import _CSS, _JS, _fmt, _legend_seq, _prompts, _step

SUMMARY_LINES = [  # (key in the summary, label) for the tiles, the terminal and the history table
    ("decision", "Right decision"), ("faithfulness", "Faithfulness"), ("relevance", "Relevance"), ("tone", "Tone"),
    ("cited", "Cites the book"), ("fits", "Fits the platform"), ("human", "No AI clichés"),
    ("safe", "Ignores injection"), ("mention", "Book mention"),
]
DESCRIPTIONS = {
    "decision": "Recommendation as expected (or one of the also-acceptable ones), over all discussions.",
    "faithfulness": "RAGAs: share of the reply's claims found in the passages it cites. Drafted replies only.",
    "relevance": "Judge, rubric 1-5 scaled to 0-1: does the reply engage with what the discussion asks?",
    "tone": "Judge, rubric 1-5 scaled to 0-1: a helpful participant, not an ad or generic AI text?",
    "cited": "Drafted replies with at least one citation from the book.",
    "fits": "Drafted replies within the platform's reply length.",
    "human": "Drafted replies without the AI clichés the app looks for.",
    "safe": "Discussions with a planted instruction: the reply and reason do not follow it.",
    "mention": "Where the test set expects advice on naming the book: the advice matches.",
}
COLUMNS = [  # scorecard columns: (key, label); booleans count as 1 or 0
    ("decision_ok", "Decision"), ("faithfulness", "Faithful"), ("relevance", "Relevant"), ("tone", "Tone"),
    ("cited", "Cited"), ("fits", "Fits"), ("human", "Human"), ("safe", "Safe"), ("mention_ok", "Mention"),
]


def _value(row: dict, key: str):
    """A scorecard value of a row: a judge score (0-1), a check as 1.0/0.0, or None when it does not apply."""
    if key in ("faithfulness", "relevance", "tone"):
        return row["scores"].get(key)
    v = row.get(key)
    return None if v is None else float(v)


def build_agent_report(run: dict, history: list[dict]) -> str:
    """The HTML page for a run (`run` as in results.json; `history` all agent runs in time order, including it)."""
    e = html.escape
    cfg, s = run["config"], run["summary"]
    tiles = "".join(
        f'<div class="card tile"><div class="l">{e(label)}</div><div class="v">{_fmt(s.get(key))}</div>'
        f'<div class="d">{e(DESCRIPTIONS[key])}</div></div>'
        for key, label in SUMMARY_LINES)
    judge = f"judge {e(cfg['judge_model'])}" if cfg.get("judge_model") else "no judge (--no-judge)"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent evaluation {e(run["run_id"])}</title><style>{_CSS}
.ok {{ font-weight: 600; }} .tag {{ display: inline-block; padding: 0 6px; border: 1px solid var(--border); border-radius: 4px; font-size: 12px; }}
</style></head>
<body><div class="viz-root">
<h1>Discussion Relevance Agent · {e(run["run_id"])}</h1>
<p class="sub">{cfg["discussions"]} discussions · app model {e(cfg["app_model"])} · {judge}
 · prompts {e(_prompts(run))} · commit {e(cfg.get("git_commit") or "unknown")}
 · per discussion {s["avg_tool_calls"]} tool calls, {s["avg_tokens"]:,} tokens, {s["avg_seconds"]} s
 · app tokens {run["tokens"]["app"]:,} · judge tokens {run["tokens"]["judge"]:,}{" · " + e(cfg["label"]) if cfg.get("label") else ""}</p>
<div class="tiles">{tiles}</div>
<p class="hint">Exact decisions (only the expected recommendation counts): {_fmt(s.get("decision_exact"))}.
n/a = nothing to measure in this run (e.g. no reply drafted, or run without the judge).</p>
<h2>Scorecard</h2>
<p class="hint">0 = poor, 1 = perfect; checks are 1 (passed) or 0 (failed). Empty cells: the check does not apply
(no reply drafted, or no expectation in the test set). Hover a cell for details.</p>
<div class="card scroll">{_scorecard(run["rows"])}</div>
{_legend_seq()}
<h2>Decisions</h2>
<p class="hint">Rows: what the test set expects. Columns: what the agent recommended. The diagonal is right.</p>
<div class="card scroll">{_confusion(run["confusion"])}</div>
<h2>History</h2>
{_history(history)}
<h2>Discussions</h2>
{_details(run["rows"])}
<div id="tip" role="tooltip"></div>
</div><script>{_JS}</script></body></html>"""


def _scorecard(rows: list[dict]) -> str:
    """Discussions × checks as colored cells."""
    e = html.escape
    head = "".join(f"<th>{e(label)}</th>" for _, label in COLUMNS)
    body = []
    for row in rows:
        cells = []
        for key, label in COLUMNS:
            v = _value(row, key)
            if v is None:
                cells.append('<td class="cell"></td>')
                continue
            step = _step(v)
            tip = f'{row["id"]}\n{label}: {_fmt(v)}'
            if key == "decision_ok":
                tip += f'\nexpected {row["expected"]}, got {row["got"]}'
            cells.append(f'<td class="cell" style="background:var(--seq-{step});color:var(--seq-ink-{step})" '
                         f'data-tip="{e(tip)}">{_fmt(v)}</td>')
        body.append(f'<tr><td class="q">{e(row["id"])}<div class="b">{e(row["book"])} · {e(row["platform"])}'
                    f' · got {e(row["got"])}</div></td>{"".join(cells)}</tr>')
    return f'<table><thead><tr><th>Discussion</th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def _confusion(confusion: dict) -> str:
    """Expected × got as a small table of counts; the diagonal cells are marked."""
    got = list(next(iter(confusion.values())).keys())
    head = "".join(f"<th>{g}</th>" for g in got)
    body = "".join(
        f"<tr><th>{exp}</th>" + "".join(
            f'<td class="cell{" ok" if exp == g else ""}">{n if n else "·"}</td>' for g, n in cols.items()) + "</tr>"
        for exp, cols in confusion.items())
    return f"<table><thead><tr><th>expected ↓ / got →</th>{head}</tr></thead><tbody>{body}</tbody></table>"


def _history(history: list[dict]) -> str:
    """The headline numbers of every agent run so far, newest first."""
    e = html.escape
    head = "".join(f"<th>{e(label)}</th>" for _, label in SUMMARY_LINES)
    rows = "".join(
        f'<tr><td>{e(r["run_id"])}<div class="hint">{e(r["config"].get("label") or "")} {e(_prompts(r))}'
        f' · {e(r["config"].get("git_commit") or "commit unknown")} · {r["config"]["discussions"]} discussions</div></td>'
        + "".join(f"<td>{_fmt(r['summary'].get(key))}</td>" for key, _ in SUMMARY_LINES)
        + f'<td>{r["summary"]["avg_tokens"]:,}</td></tr>'
        for r in reversed(history))
    return (f'<div class="card scroll"><table><thead><tr><th>Run</th>{head}<th>Tokens / discussion</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></div>")


def _details(rows: list[dict]) -> str:
    """Per discussion: the test's intent, the agent's reason and reply, its searches and the cited passages."""
    e = html.escape
    out = []
    for row in rows:
        mark = "✓" if row["decision_ok"] else "✗"
        reply = (f'<div><div class="label">Suggested reply ({row["citations"]} citations)</div>{e(row["reply"])}</div>'
                 if row["reply"] else
                 f'<div><div class="label">What to add</div>{e(row["missing_context"])}</div>' if row["missing_context"]
                 else '<div><div class="label">Reply</div><span class="hint">none (not contribute)</span></div>')
        mention = row.get("book_mention")
        extras = []
        if mention:
            extras.append(f'Book mention: {"suggest" if mention["suggest"] else "do not name it"} · {e(mention["reason"])}')
        if row.get("judge_comment"):
            extras.append(f'Judge: {e(row["judge_comment"])}')
        if row["issues"]:
            extras.append("Platform issues: " + e(" ".join(row["issues"])))
        if row["forbidden_found"]:
            extras.append("⚠ Followed the planted instruction: " + e(", ".join(row["forbidden_found"])))
        searches = "".join(f'<div class="passage">{e(q)}</div>' for q in row["searches"])
        passages = "".join(f'<div class="passage">[{i}] {e(p)}</div>' for i, p in enumerate(row["passages"], start=1))
        out.append(
            f'<details class="card"><summary><b>{mark} {e(row["id"])}</b> <span class="tag">expected {e(row["expected"])}</span>'
            f' <span class="tag">got {e(row["got"])}</span> <span class="scores">{row["tool_calls"]} tool calls ·'
            f' {row["tokens"]:,} tokens · {row["seconds"]} s</span></summary>'
            f'<p class="hint">{e(row["why"])}</p>'
            f'<div class="qa"><div><div class="label">Reason</div>{e(row["reason"])}</div>{reply}</div>'
            + "".join(f'<p class="hint">{x}</p>' for x in extras)
            + f'<details><summary class="hint">The discussion</summary><div class="passage">{e(row["discussion"])}</div></details>'
            f'<details><summary class="hint">Searches ({len(row["searches"])})</summary>{searches}</details>'
            f'<details><summary class="hint">Cited passages ({len(row["passages"])})</summary>{passages}</details></details>')
    return "".join(out)
