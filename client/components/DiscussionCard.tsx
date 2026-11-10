"use client";

/**
 * A saved result of the Discussion Relevance Agent as a card: the recommendation and its reason, what is missing
 * (more_context), the reply the author can edit and copy, the advice on naming the book, the cited passages and,
 * collapsed, the discussion itself and the agent's trace (searches and tool calls).
 */

import { useState, type ReactNode } from "react";
import {
  AlertTriangle, BookMarked, Check, CircleSlash, Copy, ExternalLink, MessageCircle, MessageSquarePlus, Pencil, Send,
  ThumbsUp, Trash2, UserCheck, X,
} from "lucide-react";
import {
  api, cleanText, DISCUSSION_PLATFORMS, errorMessage, humanizeLabel, TONES, type DiscussionAnalysis, type Recommendation,
} from "@/lib/api";
import { CitationList, TextWithMarkers } from "./AssetCard";
import ToolCallCard from "./ToolCallCard";
import { Badge, Button, ErrorNote } from "./ui";

/** How each recommendation is shown. */
const RECOMMENDATIONS: Record<Recommendation, { label: string; tone: "success" | "warning" | "neutral"; icon: typeof ThumbsUp }> = {
  contribute: { label: "Contribute", tone: "success", icon: ThumbsUp },
  more_context: { label: "Needs more context", tone: "warning", icon: MessageSquarePlus },
  skip: { label: "Skip", tone: "neutral", icon: CircleSlash },
};

/** A framed block with a small label, like the "Replying to" box of the asset cards. */
function Boxed({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="bc-cite-src" style={{ borderLeft: 0, borderRadius: "var(--radius-md)", padding: 12 }}>
      <div className="bc-label">{label}</div>
      {children}
    </div>
  );
}

/**
 * One analysis with its actions: Copy (the reply without citation markers), Edit (save the author's version),
 * Open discussion (the pasted link, in a new tab) and Delete. For a comment on the author's Facebook Page also
 * "Reply as Page" (once; then a link to the posted reply).
 * @param analysis The saved analysis.
 * @param book Readable title of its book, shown when the list is not limited to one book.
 * @param onChange Called after the reply was saved or the analysis deleted, to reload the list.
 */
export default function DiscussionCard({ analysis: a, book, onChange }: {
  analysis: DiscussionAnalysis; book?: string; onChange: () => void;
}) {
  const [draft, setDraft] = useState<string | null>(null); // reply being edited; null = not editing
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);
  const [replying, setReplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const rec = RECOMMENDATIONS[a.recommendation];
  const platform = DISCUSSION_PLATFORMS.find((p) => p.value === a.platform);
  const hasReply = a.reply.trim() !== "";
  const publishable = cleanText(a.reply);
  const words = publishable.split(/\s+/).filter(Boolean).length;
  const limit = platform?.replyLimit;
  const overLimit = limit != null && publishable.length > limit;
  const aiTells = a.platform_issues.find((i) => i.startsWith("Sounds AI-written")) ?? "";
  const openLink = a.url ? ( // shown next to the reply, or in the footer when there is no reply
    <a className="bc-btn bc-btn-ghost bc-btn-sm" href={a.url} target="_blank" rel="noopener noreferrer" title={a.url}>
      <ExternalLink size={14} className="bc-ico" aria-hidden />Open discussion
    </a>
  ) : null;
  const when = new Date(a.created_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

  /** Copy the reply without citation markers, ready to paste on the platform. */
  async function copy() {
    try {
      await navigator.clipboard.writeText(publishable);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Could not copy to the clipboard.");
    }
  }

  /** Save the edited reply (PATCH /discussions/{id}) and reload the list. */
  async function save() {
    if (draft === null || !draft.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await api.updateDiscussion(a.id, draft.trim());
      setDraft(null);
      onChange();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  /** After a confirmation showing the exact text, post the reply as the Page under the comment. */
  async function replyAsPage() {
    if (!window.confirm(`Post this reply as your Facebook Page now? Everyone can see it.\n\n${publishable}`)) return;
    setReplying(true);
    setError(null);
    try {
      await api.replyOnFacebook(a.id);
      onChange();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setReplying(false);
    }
  }

  /** Delete the analysis after confirmation and reload the list. */
  async function remove() {
    if (!window.confirm("Delete this discussion analysis?")) return;
    try {
      await api.deleteDiscussion(a.id);
      onChange();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <article className="bc-out">
      <div className="bc-out-h" style={{ flexWrap: "wrap" }}>
        <strong>{book ?? "Discussion analysis"}</strong>
        <Badge tone={rec.tone} icon={rec.icon}>{rec.label}</Badge>
        {a.facebook_comment_id ? <Badge tone="accent" icon={MessageCircle}>Your Facebook Page</Badge> : platform && <Badge>{platform.label}</Badge>}
        {a.replied_url && <Badge tone="success" icon={Send}>replied</Badge>}
        {a.tone && a.tone !== "neutral" && <Badge>{TONES.find((t) => t.value === a.tone)?.label ?? a.tone}</Badge>}
        {a.edited && <Badge tone="warning" icon={Pencil}>edited</Badge>}
        {hasReply && (
          <span title={`Written with "how human" ${a.humanize} (${humanizeLabel(a.humanize)}). ${aiTells ? aiTells : "No AI-typical wording found."}`}>
            <Badge tone={aiTells ? "warning" : "success"} icon={UserCheck}>human {a.humanize}</Badge>
          </span>
        )}
        <Badge mono>{when}</Badge>
        <Button variant="ghost" size="sm" icon={Trash2} onClick={remove} title="Delete this analysis">Delete</Button>
      </div>

      <details>
        <summary className="bc-hint" style={{ cursor: "pointer" }}>
          The discussion ({a.discussion.length.toLocaleString()} characters){a.angle && <> · your angle: {a.angle}</>}
        </summary>
        <blockquote style={{ whiteSpace: "pre-wrap", margin: "8px 0 0", maxHeight: 320, overflow: "auto" }}
          className="bc-cite-src">{a.discussion}</blockquote>
      </details>

      <Boxed label="Why">
        <TextWithMarkers text={a.reason} />
      </Boxed>

      {a.missing_context && (
        <Boxed label="What to add">
          <p style={{ margin: 0 }}>{a.missing_context}</p>
          <span className="bc-hint">Paste the discussion again with this added, and analyse it once more.</span>
        </Boxed>
      )}

      {(hasReply || draft !== null) && (
        <div className="bc-stack" style={{ gap: 8 }}>
          {/* The posting actions sit with the reply: copy it (without markers), then open the discussion to paste it. */}
          <div className="bc-row" style={{ gap: 8 }}>
            <div className="bc-label" style={{ flex: 1 }}>{a.edited ? "Your reply" : "Suggested reply"}</div>
            {draft === null && (
              <>
                <Button variant={copied ? "success" : "secondary"} size="sm" icon={copied ? Check : Copy} onClick={copy}
                  title="Copy the reply without the [n] citation markers, ready to paste">
                  {copied ? "Copied" : "Copy for posting"}
                </Button>
                {a.facebook_comment_id && !a.replied_url && (
                  <Button size="sm" icon={Send} loading={replying} onClick={replyAsPage} disabled={overLimit}
                    title="Post the reply (without citation markers) under the comment, as your Page">Reply as Page</Button>
                )}
                {openLink}
                <Button variant="ghost" size="sm" icon={Pencil} onClick={() => setDraft(a.reply)}>Edit</Button>
              </>
            )}
          </div>
          {a.replied_url && draft === null && (
            <span className="bc-hint">
              Posted as your Page{a.replied_at ? ` on ${new Date(a.replied_at).toLocaleString()}` : ""}:{" "}
              <a href={a.replied_url} target="_blank" rel="noopener noreferrer">open the reply <ExternalLink size={12} aria-hidden /></a>
              {" "}Later edits here do not change it on Facebook.
            </span>
          )}
          {draft === null ? (
            <TextWithMarkers text={a.reply} />
          ) : (
            <>
              <textarea className="bc-textarea" rows={Math.min(16, Math.max(5, draft.split("\n").length + 2))}
                value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="Edit the reply" />
              <div className="bc-row" style={{ gap: 8 }}>
                <Button size="sm" variant="success" icon={Check} loading={saving} onClick={save}>Save</Button>
                <Button size="sm" variant="ghost" icon={X} onClick={() => setDraft(null)}>Cancel</Button>
                {a.edited && (
                  <Button size="sm" variant="ghost" onClick={() => setDraft(a.suggested_reply)}
                    title="Put the agent's original suggestion back into the editor">Use the suggestion again</Button>
                )}
              </div>
            </>
          )}
          {!a.edited && a.platform_issues.length > 0 && draft === null && (
            <span className="bc-hint" style={{ color: "var(--warning-text)", display: "flex", gap: 6 }}>
              <AlertTriangle size={14} className="bc-ico" aria-hidden style={{ flex: "none", marginTop: 2 }} />
              {a.platform_issues.join(" ")}
            </span>
          )}
        </div>
      )}

      {a.book_mention && (
        <div className="bc-row" style={{ gap: 8, flexWrap: "nowrap", alignItems: "baseline" }}>
          <span style={{ flex: "none" }}>
            <Badge tone={a.book_mention.suggest ? "accent" : "neutral"} icon={BookMarked}>
              {a.book_mention.suggest ? "Mention the book" : "Don't name the book"}
            </Badge>
          </span>
          <span className="bc-hint">{a.book_mention.reason}</span>
        </div>
      )}

      <CitationList citations={a.citations} />

      {(a.search_queries.length > 0 || a.tool_calls.length > 0) && (
        <details>
          <summary className="bc-hint" style={{ cursor: "pointer" }}>
            How the agent worked: {a.tool_calls.length} tool calls, {a.search_queries.length} searches
            {a.tokens > 0 && <> · {a.tokens.toLocaleString()} tokens</>}{a.model && <> · {a.model}</>}
          </summary>
          <div className="bc-stack" style={{ gap: 8, marginTop: 8 }}>
            {a.tool_calls.map((call, i) => <ToolCallCard key={i} call={call} />)}
            {a.prompt_version && <span className="bc-hint bc-mono">prompts {a.prompt_version} · {a.id}</span>}
          </div>
        </details>
      )}
      {error && <ErrorNote>{error}</ErrorNote>}

      <div className="bc-out-f" style={{ flexWrap: "wrap" }}>
        {hasReply && (
          <>
            <span>{words} words</span>
            <span style={overLimit ? { color: "var(--danger-text)", fontWeight: 600 } : undefined}
              title={limit != null ? `${platform?.label} reply limit: ${limit.toLocaleString()} characters (without citation markers)` : undefined}>
              · {publishable.length.toLocaleString()}{limit != null ? ` / ${limit.toLocaleString()}` : ""} chars{overLimit ? " (too long)" : ""}
            </span>
          </>
        )}
        <span>{hasReply ? "· " : ""}{a.citations.length} citations</span>
        <span style={{ flex: 1 }} />
        {!hasReply && openLink}
      </div>
    </article>
  );
}
