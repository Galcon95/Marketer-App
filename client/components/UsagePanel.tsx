"use client";

/**
 * The "LLM usage & costs" drawer opened from the top bar: totals and the history of model calls
 * (GET /usage), plus the token and USD formatters the top bar uses too.
 */

import { Cpu } from "lucide-react";
import { api, type UsageTotals } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { Badge, Drawer, ErrorNote, Placeholder } from "./ui";

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

/**
 * Side panel with the usage log of all model calls (GET /usage): totals for input ("upload"),
 * output ("download") and all costs, totals per operation, and the latest calls. Loads fresh data
 * each time it is opened.
 * @param openCount Increases each time the panel is opened, so the data is reloaded.
 * @param onClose Called to close the panel.
 */
export default function UsageDrawer({ openCount, onClose }: { openCount: number; onClose: () => void }) {
  const usage = useApi(`usage-panel:${openCount}`, () => api.usage(50));
  const report = usage.data;
  return (
    <Drawer icon={Cpu} title="LLM usage & costs" label="LLM usage and costs" onClose={onClose}
      meta={report ? <Badge mono>{report.totals.calls} calls</Badge> : undefined}>
      <span className="bc-hint">
        Every model call is logged in server/assets/usage/usage.jsonl. Chat costs are the exact amounts
        reported by OpenRouter; embedding costs are estimated from the price list (input tokens only).
      </span>
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
