"use client";

/**
 * The "LLM usage & costs" drawer opened from the top bar: the user's budget, totals and the history of model calls
 * (GET /usage), plus the token and USD formatters the top bar uses too.
 */

import { useState } from "react";
import { Cpu, Download } from "lucide-react";
import { api, downloadUsage, errorMessage, type UsageBudget, type UsagePeriod, type UsageTotals } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { Badge, Button, Drawer, ErrorNote, Placeholder, ProgressBar } from "./ui";

/**
 * Compact token count, e.g. 950 → "950", 12_340 → "12.3k", 2_500_000 → "2.5M".
 * @param n Number of tokens.
 */
export function formatTokens(n: number) {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}

/**
 * USD amount with enough decimals for fractions of a cent, e.g. "$0.000486", "$0.0153", "$1.24".
 * @param amount Amount in USD.
 */
export function formatUsd(amount: number) {
  if (amount === 0) return "$0";
  if (amount < 0.01) return `$${amount.toFixed(6)}`;
  if (amount < 1) return `$${amount.toFixed(4)}`;
  return `$${amount.toFixed(2)}`;
}

const PERIODS: { value: UsagePeriod; label: string }[] = [
  { value: "this_month", label: "This month" },
  { value: "last_month", label: "Last month" },
  { value: "all", label: "All time" },
];

/**
 * Period choice and a button that downloads the usage as an Excel workbook (sheets Calls, By day, By operation).
 * @param scope Whose calls: the user's own or (admin) the whole app's, as shown in the panel.
 */
function ExcelExport({ scope }: { scope: "me" | "app" }) {
  const [period, setPeriod] = useState<UsagePeriod>("this_month");
  const [pending, setPending] = useState(false);
  const [note, setNote] = useState<{ error: boolean; text: string } | null>(null);

  async function download() {
    setPending(true);
    setNote(null);
    try {
      setNote({ error: false, text: `Saved as ${await downloadUsage(period, scope)}.` });
    } catch (err) {
      setNote({ error: true, text: errorMessage(err) });
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="bc-stack" style={{ gap: 6 }}>
      <div className="bc-row" style={{ gap: "var(--space-2)", flexWrap: "nowrap" }}>
        <div className="bc-select-wrap" style={{ flex: 1 }}>
          <select className="bc-select" aria-label="Period to export" value={period}
            onChange={(e) => setPeriod(e.target.value as UsagePeriod)}>
            {PERIODS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
        </div>
        <Button size="sm" variant="secondary" icon={Download} loading={pending} onClick={download}
          title="Download the calls as an Excel file: every call, per day and per operation">
          Excel
        </Button>
      </div>
      {note && (note.error ? <ErrorNote>{note.text}</ErrorNote> : <span className="bc-hint">{note.text}</span>)}
    </div>
  );
}

/**
 * Side panel with the usage log of the user's model calls (GET /usage): their budget for today and this month,
 * totals for input ("upload"), output ("download") and all costs, totals per operation, and the latest calls.
 * The admin can switch to all users' calls. Loads fresh data each time it is opened or switched.
 * @param openCount Increases each time the panel is opened, so the data is reloaded.
 * @param onClose Called to close the panel.
 * @param admin Show the switch between "Mine" and "Whole app".
 */
export default function UsageDrawer({ openCount, onClose, admin }: { openCount: number; onClose: () => void; admin?: boolean }) {
  const [scope, setScope] = useState<"me" | "app">("me");
  const usage = useApi(`usage-panel:${openCount}:${scope}`, () => api.usage(50, scope));
  const report = usage.data;
  return (
    <Drawer icon={Cpu} title="LLM usage & costs" label="LLM usage and costs" onClose={onClose}
      meta={report ? <Badge mono>{report.totals.calls} calls</Badge> : undefined}>
      {admin && (
        <div style={{ display: "flex", gap: "var(--space-2)" }}>
          <Button size="sm" variant={scope === "me" ? "primary" : "secondary"} onClick={() => setScope("me")}>Mine</Button>
          <Button size="sm" variant={scope === "app" ? "primary" : "secondary"} onClick={() => setScope("app")}>Whole app</Button>
        </div>
      )}
      {report && <Budget budget={report.budget} />}
      <span className="bc-hint">
        {scope === "app" ? "All users' model calls." : "Your own model calls."} Chat costs are the exact amounts
        reported by OpenRouter; embedding costs are estimated from the price list (input tokens only).
      </span>
      <ExcelExport scope={scope} />
      {usage.error ? (
        <ErrorNote>{usage.error}</ErrorNote>
      ) : !report ? (
        <Placeholder icon={Cpu}>Loading…</Placeholder>
      ) : report.totals.calls === 0 ? (
        <Placeholder icon={Cpu}>No model calls yet.</Placeholder>
      ) : (
        <>
          <div className="bc-label">Total so far</div>
          <TotalsTable rows={[["All calls", report.totals]]} />

          <div className="bc-label">By operation</div>
          <TotalsTable rows={Object.entries(report.by_operation)} />

          <div className="bc-label">Latest calls</div>
          <div className="bc-table-wrap">
            <table className="bc-table">
              <thead>
                <tr><th>Time</th><th>Operation</th><th>Model</th><th>In tok</th><th>Out tok</th><th>Cost</th></tr>
              </thead>
              <tbody>
                {report.recent.map((r, i) => (
                  <tr key={i} title={`input ${formatUsd(r.input_cost)} · output ${formatUsd(r.output_cost)} · ${r.cost_source === "provider" ? "cost reported by OpenRouter" : "estimated from price list"}`}>
                    <td className="bc-mono">{new Date(r.timestamp).toLocaleTimeString()}</td>
                    <td className="bc-mono">{r.operation}</td>
                    <td className="bc-mono">{r.model.split("/").pop()}</td>
                    <td className="bc-mono">{r.input_tokens.toLocaleString()}</td>
                    <td className="bc-mono">{r.output_tokens.toLocaleString()}</td>
                    <td className="bc-mono">{formatUsd(r.cost)}{r.cost_source === "estimate" ? "*" : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <span className="bc-hint">* estimated from the price list. Hover a row for the input/output split.</span>
        </>
      )}
    </Drawer>
  );
}

/**
 * The user's cost budget: spent today and this month against the limits (server/limits.toml). When a budget is used
 * up, the server answers model requests with "budget used up" until it renews.
 * @param budget Spending and limits in USD.
 */
function Budget({ budget }: { budget: UsageBudget }) {
  const rows: [string, number, number, string][] = [
    ["Today", budget.spent_today, budget.limit_today, "Renews at midnight UTC"],
    ["This month", budget.spent_month, budget.limit_month, "Renews on the 1st (UTC)"],
  ];
  return (
    <>
      <div className="bc-label">Your budget</div>
      {rows.map(([label, spent, limit, renews]) => (
        <div key={label} title={renews} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span className="bc-hint">{label}: {formatUsd(spent)} of {formatUsd(limit)}</span>
          <ProgressBar value={Math.min(100, (spent / limit) * 100)} />
        </div>
      ))}
    </>
  );
}

/**
 * Table of usage totals: calls, input tokens and cost, output tokens and cost, total cost.
 * @param rows [label, totals] pairs, one row each.
 */
function TotalsTable({ rows }: { rows: [string, UsageTotals][] }) {
  return (
    <div className="bc-table-wrap">
      <table className="bc-table">
        <thead>
          <tr><th /><th>Calls</th><th>Input tok</th><th>Input $</th><th>Output tok</th><th>Output $</th><th>Total $</th></tr>
        </thead>
        <tbody>
          {rows.map(([label, t]) => (
            <tr key={label}>
              <td className="bc-mono">{label}</td>
              <td className="bc-mono">{t.calls}</td>
              <td className="bc-mono">{t.input_tokens.toLocaleString()}</td>
              <td className="bc-mono">{formatUsd(t.input_cost)}</td>
              <td className="bc-mono">{t.output_tokens.toLocaleString()}</td>
              <td className="bc-mono">{formatUsd(t.output_cost)}</td>
              <td className="bc-mono"><strong>{formatUsd(t.cost)}</strong></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
