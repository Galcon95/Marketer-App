/**
 * Prompt-injection flags for other people's text (Reddit threads, Facebook comments, pasted discussions): the server's
 * guard scans it and flags it, it never blocks it. The badge says so in one word; hovering shows what was found.
 */

import { ShieldAlert } from "lucide-react";
import type { InjectionRisk } from "@/lib/api";
import { Badge } from "./ui";

/** Plain-language names of the guard's rules, for the tooltip. */
const RULES: Record<string, string> = {
  override_instructions: "tells the AI to ignore its instructions",
  new_instructions: "gives the AI new instructions",
  role_change: "tries to change the AI's role",
  jailbreak: "jailbreak wording",
  prompt_leak: "asks for the AI's instructions",
  fake_role_marker: "pretends to be a system message",
  hide_from_user: "asks the AI to hide something from you",
  exfiltration: "tries to send data to a link",
  tool_command: "tells the AI to run a tool",
  encoded_blob: "a long encoded block",
  hidden_characters: "hidden characters",
};

/** "rule: excerpt" findings as readable lines. */
export function describeFindings(findings: string[]): string {
  return findings.map((f) => {
    const [rule, ...rest] = f.split(": ");
    return `${RULES[rule] ?? rule}: ${rest.join(": ")}`;
  }).join("\n");
}

/** The rules of the findings in plain language, e.g. "tells the AI to ignore its instructions, hidden characters". */
export function findingRules(findings: string[]): string {
  return [...new Set(findings.map((f) => RULES[f.split(": ")[0]] ?? f.split(": ")[0]))].join(", ");
}

/**
 * A badge for a text's injection risk; nothing for "none".
 * @param risk The guard's risk.
 * @param findings What it found ("rule: excerpt"), shown on hover.
 */
export default function InjectionBadge({ risk, findings }: { risk: InjectionRisk | undefined; findings: string[] | undefined }) {
  if (!risk || risk === "none") return null;
  const high = risk === "high";
  const title = (high
    ? "This text contains phrases that look like instructions to an AI (a prompt injection). It is only ever given to "
      + "the agent as quoted data, with a warning not to follow it. Check the reply before posting.\n\n"
    : "Weak signals only, e.g. hidden characters. Shown so you know; the text is treated as data.\n\n")
    + describeFindings(findings ?? []);
  return (
    <span title={title}>
      <Badge tone={high ? "danger" : "warning"} icon={ShieldAlert}>{high ? "possible prompt injection" : "unusual text"}</Badge>
    </span>
  );
}
