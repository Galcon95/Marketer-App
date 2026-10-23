"""Self-contained HTML report of one evaluation run (no internet, no libraries: inline SVG, CSS and a little JS).

    tiles      the four metric averages of this run
    heatmap    questions × metrics, one cell per score (sequential blue by the shortfall from 1: strong = weak spot), hover for details
    history    one line per metric over all runs so far (from the second run on), with a table view
    details    per question: answer, reference, retrieved passages (collapsed)

Light and dark mode follow the viewer's system setting. Colors are the dataviz reference palette
(categorical slots 1-4, validated for both modes; light slots 3-4 are below 3:1 contrast, so the
history lines carry direct labels and a table view).
"""

import html
import json
import math

METRICS = [  # (key in the results, label, what it measures)
    ("faithfulness", "Faithfulness", "Does the answer stay with the retrieved passages (no made-up claims)?"),
    ("answer_relevancy", "Answer relevancy", "Does the answer address the question?"),
    ("context_precision", "Context precision", "Are the relevant passages ranked at the top?"),
    ("context_recall", "Context recall", "Do the passages contain everything the reference answer needs?"),
]

_CSS = """
:root {
  color-scheme: light;
  --surface-0: #f4f4f2; --surface-1: #fcfcfb; --border: #e3e2de;
  --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #77766f;
  --grid: #e3e2de;
  --series-1: #2a78d6; --series-2: #eb6834; --series-3: #1baf7a; --series-4: #eda100;
  --seq-0: #f0efec; --seq-1: #cde2fb; --seq-2: #9ec5f4; --seq-3: #6da7ec; --seq-4: #3987e5; --seq-5: #256abf; --seq-6: #184f95; --seq-7: #0d366b;
  --seq-ink-0: #0b0b0b; --seq-ink-1: #0b0b0b; --seq-ink-2: #0b0b0b; --seq-ink-3: #0b0b0b; --seq-ink-4: #ffffff; --seq-ink-5: #ffffff; --seq-ink-6: #ffffff; --seq-ink-7: #ffffff;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --surface-0: #111110; --surface-1: #1a1a19; --border: #33332f;
    --text-primary: #f0efec; --text-secondary: #c3c2b7; --text-muted: #94938a;
    --grid: #33332f;
    --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70; --series-4: #c98500;
    --seq-0: #262624; --seq-1: #0d366b; --seq-2: #104281; --seq-3: #184f95; --seq-4: #256abf; --seq-5: #3987e5; --seq-6: #6da7ec; --seq-7: #b7d3f6;
    --seq-ink-0: #f0efec; --seq-ink-1: #f0efec; --seq-ink-2: #f0efec; --seq-ink-3: #f0efec; --seq-ink-4: #ffffff; --seq-ink-5: #0b0b0b; --seq-ink-6: #0b0b0b; --seq-ink-7: #0b0b0b;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--surface-0); color: var(--text-primary); font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
.viz-root { max-width: 1100px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 22px; margin: 0 0 4px; } h2 { font-size: 16px; margin: 32px 0 8px; }
.sub { color: var(--text-secondary); margin: 0 0 20px; }
.hint { color: var(--text-muted); font-size: 12px; }
.card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
.tile .v { font-size: 32px; font-weight: 650; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
.tile .l { font-weight: 600; } .tile .d { color: var(--text-secondary); font-size: 12px; }
.scroll { overflow-x: auto; }
table { border-collapse: separate; border-spacing: 2px; width: 100%; }
th { text-align: left; font-weight: 600; color: var(--text-secondary); font-size: 12px; padding: 4px 6px; }
td { padding: 6px 8px; vertical-align: top; }
td.q { color: var(--text-primary); min-width: 240px; } td.q .b { color: var(--text-muted); font-size: 12px; }
td.cell { text-align: center; font-variant-numeric: tabular-nums; border-radius: 4px; min-width: 92px; cursor: default; }
.legend { display: flex; flex-wrap: wrap; gap: 14px; margin: 8px 0 0; color: var(--text-secondary); font-size: 12px; align-items: center; }
.legend .sw { display: inline-block; width: 18px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: middle; }
.legend .ln { display: inline-block; width: 18px; height: 2px; margin-right: 6px; vertical-align: middle; }
details { margin: 8px 0; } summary { cursor: pointer; }
.qa { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 8px; }
@media (max-width: 700px) { .qa { grid-template-columns: 1fr; } }
.qa div { white-space: pre-wrap; } .label { font-size: 12px; font-weight: 600; color: var(--text-secondary); }
.passage { border-left: 2px solid var(--border); padding: 2px 10px; margin: 6px 0; color: var(--text-secondary); font-size: 13px; white-space: pre-wrap; }
.scores { font-variant-numeric: tabular-nums; color: var(--text-secondary); font-size: 12px; }
.warn { color: var(--text-primary); font-size: 12px; font-weight: 600; margin: 2px 0 4px; }
#tip { position: fixed; pointer-events: none; z-index: 10; max-width: 320px; background: var(--surface-1); color: var(--text-primary);
  border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; font-size: 12px; box-shadow: 0 4px 16px rgba(0,0,0,.15); display: none; }
svg text { fill: var(--text-secondary); font-size: 11px; }
"""

_JS = """
const tip = document.getElementById('tip');
function showTip(e, text) { tip.textContent = text; tip.style.display = 'block'; moveTip(e); }
function moveTip(e) { const x = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 8); tip.style.left = x + 'px'; tip.style.top = (e.clientY + 14) + 'px'; }
function hideTip() { tip.style.display = 'none'; }
document.querySelectorAll('[data-tip]').forEach(el => {
  el.addEventListener('mouseenter', e => showTip(e, el.dataset.tip));
  el.addEventListener('mousemove', moveTip);
  el.addEventListener('mouseleave', hideTip);
});
// History chart: crosshair + tooltip with all four metrics of the nearest run.
const hist = document.getElementById('history');
if (hist) {
  const runs = JSON.parse(hist.dataset.runs), xs = JSON.parse(hist.dataset.xs), cross = hist.querySelector('.cross');
  hist.addEventListener('mousemove', e => {
    const box = hist.getBoundingClientRect(), x = (e.clientX - box.left) * (hist.viewBox.baseVal.width / box.width);
    let i = 0; xs.forEach((v, j) => { if (Math.abs(v - x) < Math.abs(xs[i] - x)) i = j; });
    cross.setAttribute('x1', xs[i]); cross.setAttribute('x2', xs[i]); cross.style.display = 'block';
    showTip(e, runs[i]);
  });
  hist.addEventListener('mouseleave', () => { cross.style.display = 'none'; hideTip(); });
}
"""


def build_report(run: dict, history: list[dict]) -> str:
    """The HTML page for a run. `run` is the results.json content of this run, `history` all runs in time order
    (including this one)."""
    e = html.escape
    cfg = run["config"]
    scored, total = _scored(run), len(run["rows"])
    tiles = "".join(
        f'<div class="card tile"><div class="l">{e(label)}</div><div class="v">{_fmt(run["averages"].get(key))}</div>'
        + (f'<div class="warn">⚠ only {scored[key]}/{total} questions scored</div>' if scored[key] < total else "")
        + f'<div class="d">{e(desc)}</div></div>'
        for key, label, desc in METRICS
    )
    incomplete = (
        '<p class="warn">⚠ Some scores are missing (judge errors or timeouts). Those averages rest on fewer questions '
        "and are not fully comparable with other runs; missing cells show n/a.</p>"
        if any(n < total for n in scored.values()) else ""
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>RAG evaluation {e(run["run_id"])}</title><style>{_CSS}</style></head>
<body><div class="viz-root">
<h1>RAG evaluation · {e(run["run_id"])}</h1>
<p class="sub">{len(run["rows"])} questions · k={cfg["k"]} · app model {e(cfg["app_model"])} · judge {e(cfg["judge_model"])}
 · app tokens {run["tokens"]["app"]:,} · judge tokens {run["tokens"]["judge"]:,}{" · " + e(cfg["label"]) if cfg.get("label") else ""}</p>
{incomplete}<div class="tiles">{tiles}</div>
<h2>Scores per question</h2>
<p class="hint">0 = poor, 1 = perfect. The color shows how far a score falls short of 1: faint cells are fine,
strong cells are the weak spots to look at. Hover a cell for the question and the score.</p>
<div class="card scroll">{_heatmap(run["rows"])}</div>
{_legend_seq()}
<h2>History</h2>
{_history(history)}
<h2>Answers and passages</h2>
{_details(run["rows"])}
<div id="tip" role="tooltip"></div>
</div><script>{_JS}</script></body></html>"""


def _scored(run: dict) -> dict[str, int]:
    """Per metric, how many questions of the run got a score (counted from the rows, so older runs work too)."""
    return {key: sum(r["scores"].get(key) is not None for r in run["rows"]) for key, _, _ in METRICS}


def _fmt_avg(run: dict, key: str) -> str:
    """A run's average for a metric, with "(7/13)" when not every question was scored."""
    scored, total = _scored(run)[key], len(run["rows"])
    return _fmt(run["averages"].get(key)) + (f" ({scored}/{total})" if scored < total else "")


def _fmt(value) -> str:
    """A score as "0.87", or "n/a" if missing (the metric failed for this question)."""
    return "n/a" if value is None or (isinstance(value, float) and math.isnan(value)) else f"{value:.2f}"


def _step(value) -> int:
    """Sequential step 1-7 for a score's shortfall from 1 (1 = perfect score, 7 = score near 0; 0 = missing),
    so the weak spots are the cells that stand out."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return 0
    return min(7, 1 + int((1 - max(0.0, min(1.0, value))) * 7))


def _heatmap(rows: list[dict]) -> str:
    """Questions × metrics as a table of colored cells, values printed (it is a scorecard, read cell by cell)."""
    e = html.escape
    head = "".join(f"<th>{e(label)}</th>" for _, label, _ in METRICS)
    body = []
    for row in rows:
        cells = []
        for key, label, _ in METRICS:
            v, s = row["scores"].get(key), _step(row["scores"].get(key))
            tip = f'{row["question"]}\n{label}: {_fmt(v)}'
            cells.append(f'<td class="cell" style="background:var(--seq-{s});color:var(--seq-ink-{s})" data-tip="{e(tip)}">{_fmt(v)}</td>')
        body.append(f'<tr><td class="q">{e(row["question"])}<div class="b">{e(row["book"])}</div></td>{"".join(cells)}</tr>')
    return f'<table><thead><tr><th>Question</th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def _legend_seq() -> str:
    """Legend of the heatmap's color steps."""
    steps = [("1.00 (perfect)", 1), ("0.50", 4), ("0.00", 7)]
    swatches = "".join(f'<span><span class="sw" style="background:var(--seq-{s})"></span>{t}</span>' for t, s in steps)
    return f'<div class="legend">{swatches}<span><span class="sw" style="background:var(--seq-0)"></span>n/a (metric failed)</span></div>'


def _history(history: list[dict]) -> str:
    """Line chart of the four averages over all runs, with direct labels, crosshair tooltip and a table view."""
    e = html.escape
    if len(history) < 2:
        return '<p class="hint">The history chart appears from the second run on (runs are compared by their averages).</p>'
    w, h, left, right, top, bottom = 760, 260, 44, 150, 12, 36
    n = len(history)
    xs = [left + (w - left - right) * (i / (n - 1)) for i in range(n)]
    # The y axis spans the data (from a multiple of 0.2 up to 1, so the 4 grid steps are round numbers), not 0-1:
    # scores usually sit close together near the top, and a line chart (unlike bars) needs no zero baseline.
    values = [v for r in history for key, _, _ in METRICS
              if (v := r["averages"].get(key)) is not None and not (isinstance(v, float) and math.isnan(v))]
    lo = max(0.0, math.floor(round((min(values, default=0) - 0.05) * 5, 9)) / 5)  # round(): 0.8 * 5 is 3.9999...
    y = lambda v: top + (h - top - bottom) * (1 - (v - lo) / (1 - lo))  # noqa: E731
    ticks = [round(lo + (1 - lo) * i / 4, 3) for i in range(5)]
    grid = "".join(
        f'<line x1="{left}" x2="{w - right}" y1="{y(t):.1f}" y2="{y(t):.1f}" stroke="var(--grid)" stroke-width="1"/>'
        f'<text x="{left - 8}" y="{y(t) + 4:.1f}" text-anchor="end">{t:.2f}</text>'
        for t in ticks
    )
    xlabels = "".join(f'<text x="{x:.1f}" y="{h - 12}" text-anchor="middle">{e(_run_label(r["run_id"]))}</text>'
                      for x, r in zip(xs, history))
    lines, labels = [], []
    for i, (key, label, _) in enumerate(METRICS, start=1):
        pts = [(x, r["averages"].get(key)) for x, r in zip(xs, history)]
        pts = [(x, v) for x, v in pts if v is not None and not (isinstance(v, float) and math.isnan(v))]
        if not pts:
            continue
        path = " ".join(f"{'M' if j == 0 else 'L'}{x:.1f},{y(v):.1f}" for j, (x, v) in enumerate(pts))
        dots = "".join(f'<circle cx="{x:.1f}" cy="{y(v):.1f}" r="4" fill="var(--series-{i})" stroke="var(--surface-1)" stroke-width="2"/>' for x, v in pts)
        lines.append(f'<path d="{path}" fill="none" stroke="var(--series-{i})" stroke-width="2" stroke-linejoin="round"/>{dots}')
        lx, lv = pts[-1]
        labels.append((y(lv), f"{label} {lv:.2f}"))
    # Direct labels at the line ends, nudged apart so they never overlap.
    labels.sort()
    placed, last = [], -1e9
    for ly, text in labels:
        ly = max(ly, last + 14)
        placed.append(f'<text x="{w - right + 10}" y="{ly + 4:.1f}" style="fill:var(--text-primary)">{e(text)}</text>')
        last = ly
    tips = ["\n".join([r["run_id"] + (f' · {r["config"]["label"]}' if r["config"].get("label") else "")]
                      + [f"{label}: {_fmt_avg(r, key)}" for key, label, _ in METRICS]) for r in history]
    svg = (f'<svg id="history" viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Metric averages per run" '
           f"data-runs='{e(json.dumps(tips))}' data-xs='{json.dumps([round(x, 1) for x in xs])}'>"
           f'{grid}{xlabels}<line class="cross" y1="{top}" y2="{h - bottom}" stroke="var(--text-muted)" stroke-width="1" style="display:none"/>'
           f'{"".join(lines)}{"".join(placed)}</svg>')
    legend = "".join(f'<span><span class="ln" style="background:var(--series-{i})"></span>{e(label)}</span>'
                     for i, (_, label, _) in enumerate(METRICS, start=1))
    head = "".join(f"<th>{e(label)}</th>" for _, label, _ in METRICS)
    rows = "".join(
        f'<tr><td>{e(r["run_id"])}<div class="hint">{e(r["config"].get("label") or "")} k={r["config"]["k"]}</div></td>'
        + "".join(f"<td>{_fmt_avg(r, key)}</td>" for key, _, _ in METRICS) + "</tr>"
        for r in history
    )
    return (f'<div class="card">{svg}<div class="legend">{legend}</div></div>'
            f'<details><summary class="hint">Table view</summary><div class="card scroll"><table><thead><tr><th>Run</th>{head}</tr></thead>'
            f"<tbody>{rows}</tbody></table></div></details>")


def _run_label(run_id: str) -> str:
    """Short axis label of a run: "2026-10-22_155427" → "10-22 15:54"."""
    date, _, clock = run_id.partition("_")
    return f"{date[5:]} {clock[:2]}:{clock[2:4]}" if len(clock) >= 4 else run_id


def _details(rows: list[dict]) -> str:
    """Per question: scores, the app's answer next to the reference answer, and the retrieved passages."""
    e = html.escape
    out = []
    for row in rows:
        scores = " · ".join(f"{label} {_fmt(row['scores'].get(key))}" for key, label, _ in METRICS)
        passages = "".join(f'<div class="passage">{e(p)}</div>' for p in row["contexts"])
        tools = f' · tools: {e(", ".join(row["tool_calls"]))}' if row.get("tool_calls") else ""
        out.append(
            f'<details class="card"><summary><b>{e(row["question"])}</b> <span class="scores">{scores}</span></summary>'
            f'<div class="qa"><div><div class="label">Answer ({row["citations"]} citations · {row["tokens"]:,} tokens{tools})</div>{e(row["answer"])}</div>'
            f'<div><div class="label">Reference</div>{e(row["reference"])}</div></div>'
            f'<details><summary class="hint">Retrieved passages ({len(row["contexts"])})</summary>{passages}</details></details>'
        )
    return "".join(out)
