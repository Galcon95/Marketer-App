"use client";

/**
 * A tool call a model made, as a collapsible card: used by the "Ask your book" chat (Knowledge Hub) and the
 * Discussion Relevance Agent's trace (Market Intelligence).
 */

import { Wrench } from "lucide-react";
import type { ToolCallRecord } from "@/lib/api";
import { Badge } from "./ui";

/** Short labels of the tools, shown on their cards. */
const TOOL_LABELS: Record<string, string> = {
  list_books: "Looked up the library",
  check_platform_fit: "Checked the post for the platform",
  draft_social_post: "Drafted a post (saved to the asset library)",
  get_book_profile: "Read the book's profile (themes, chapters)",
  search_book_material: "Searched the book",
};

/** One-line summary of a call's arguments: the search query if there is one, else the JSON (shortened). */
function argumentsLine(args: Record<string, unknown>) {
  if (typeof args.query === "string") return `“${args.query}”`;
  const json = JSON.stringify(args);
  return json === "{}" ? "" : json.length > 300 ? json.slice(0, 297) + "…" : json;
}

/**
 * A tool the model called: what it did, with which arguments, whether it worked and how long it took; the full
 * result (JSON) is collapsed below.
 * @param call The tool call.
 */
export default function ToolCallCard({ call }: { call: ToolCallRecord }) {
  const args = argumentsLine(call.arguments);
  return (
    <details className="bc-cite-src" style={{ borderLeft: 0, borderRadius: "var(--radius-md)" }}>
      <summary className="bc-row" style={{ gap: 8, cursor: "pointer", flexWrap: "wrap" }}>
        <Badge tone={call.ok ? "accent" : "danger"} icon={Wrench} mono>{call.name}</Badge>
        <span className="bc-hint">{call.ok ? TOOL_LABELS[call.name] ?? "Called a tool" : "Tool call failed"}</span>
        {args && <span className="bc-hint" style={{ wordBreak: "break-word" }}>{args}</span>}
        <Badge mono>{call.duration_ms} ms</Badge>
      </summary>
      <pre className="bc-mono" style={{ margin: "8px 0 0", padding: 10, maxHeight: 300, overflow: "auto", fontSize: 12,
        whiteSpace: "pre-wrap", wordBreak: "break-word", background: "var(--surface-sunken)",
        border: "1px solid var(--border)", borderRadius: "var(--radius-md)" }}>
        {typeof call.result === "string" ? call.result : JSON.stringify(call.result, null, 2)}
      </pre>
    </details>
  );
}
