"use client";

import { useState } from "react";
import { AlertTriangle, Check, Copy, Pencil, ShieldCheck, Sparkles, Trash2, UserCheck, X } from "lucide-react";
import { api, assetTypeLabel, cleanText, errorMessage, humanizeLabel, locationLabel, PLATFORMS, type Asset, type Citation, type VerifyItem } from "@/lib/api";
import { PageLink } from "./BookCover";
import { Badge, Button, ErrorNote, Score } from "./ui";

/**
 * Numbered list of cited passages ([1], [2], ... matching the markers in a generated text), each
 * with its location (click: opens the PDF at that page), chunk id, similarity and quote. Renders nothing if there are no citations.
 * @param citations The citations, in marker order.
 */
export function CitationList({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;
  return (
    <div className="bc-stack" style={{ gap: 8 }}>
      <div className="bc-label">Cited sources</div>
      {citations.map((c, i) => (
        <div key={c.chunk_id} className="bc-cite-src" style={{ borderLeft: 0, borderRadius: "var(--radius-md)" }}>
          <div className="bc-cite-k">
            <Badge tone="accent" mono>[{i + 1}]</Badge>
            <PageLink sourceId={c.source_id} page={c.location.page}><Badge mono>{locationLabel(c.location)}</Badge></PageLink>
            <Badge mono>{c.chunk_id}</Badge>
            <Score label="sim" value={c.score} />
          </div>
          <blockquote>{c.quote}</blockquote>
        </div>
      ))}
    </div>
  );
}

/**
 * A text with its [n] citation markers shown as small superscripts (the markers stay in the data;
 * Copy uses the text without them).
 * @param text Generated text with markers.
 */
function TextWithMarkers({ text }: { text: string }) {
  return (
    // pre-wrap keeps the line breaks of multi-line assets (newsletter, ad variants, persona, Instagram).
    <p style={{ whiteSpace: "pre-wrap", margin: 0 }}>
      {text.split(/(\[\d+\])/).map((part, i) =>
        /^\[\d+\]$/.test(part)
          ? <sup key={i} style={{ color: "var(--accent-text)", fontSize: "0.7em", marginLeft: 1 }}>{part}</sup>
          : part,
      )}
    </p>
  );
}

/**
 * A generated asset with its sources and actions.
 * Shows the post it replies to (replies), the asset text with superscript citation markers, its
 * cited sources (numbered like the markers), the "how human" level with any AI-typical wording left,
 * word and character counts (against the platform limit
 * for social posts and replies), and actions: Copy (publishable text without markers), Edit (save
 * a changed text), Verify (check each sentence against the project's sources, POST /verify) and
 * Delete.
 * @param asset The asset to display.
 * @param onChange Called after the asset was edited or deleted, to reload the asset list.
 */
export default function AssetCard({ asset, onChange }: { asset: Asset; onChange: () => void }) {
  const [checks, setChecks] = useState<VerifyItem[] | null>(null); // null until Verify was pressed
  const [verifying, setVerifying] = useState(false);
  const [draft, setDraft] = useState<string | null>(null); // text being edited; null = not editing
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const publishable = cleanText(asset.text);
  const words = publishable.split(/\s+/).filter(Boolean).length;
  const platform = PLATFORMS.find((p) => p.value === asset.platform);
  const limit = platform && (asset.asset_type === "social_reply" ? platform.replyLimit : platform.postLimit);
  const overLimit = limit != null && publishable.length > limit;

  /** Send the publishable text to POST /verify and store the per-claim results (or the error). */
  async function verify() {
    setVerifying(true);
    setError(null);
    try {
      setChecks((await api.verify(publishable)).items);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setVerifying(false);
    }
  }

  /** Copy the publishable text (without citation markers) to the clipboard. */
  async function copy() {
    try {
      await navigator.clipboard.writeText(publishable);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Could not copy to the clipboard.");
    }
  }

  /** Save the edited text (PATCH /assets/{id}) and reload the list. */
  async function save() {
    if (draft === null || !draft.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await api.updateAsset(asset.id, draft.trim());
      setDraft(null);
      setChecks(null); // the old verification belongs to the old text
      onChange();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  /** Delete the asset after confirmation and reload the list. */
  async function remove() {
    if (!window.confirm(`Delete this ${assetTypeLabel(asset.asset_type).toLowerCase()}?`)) return;
    try {
      await api.deleteAsset(asset.id);
      onChange();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <article className="bc-out">
      <div className="bc-out-h" style={{ flexWrap: "wrap" }}>
        <strong>{assetTypeLabel(asset.asset_type)}</strong>
        {asset.grounded
          ? <Badge tone="success" icon={ShieldCheck}>Grounded</Badge>
          : <Badge icon={Sparkles}>Zero-shot</Badge>}
        {platform && <Badge>{platform.label}</Badge>}
        {asset.tone !== "neutral" && <Badge>{asset.tone}</Badge>}
        {!platform && asset.length !== "standard" && <Badge>{asset.length}</Badge>}
        {asset.edited && <Badge tone="warning" icon={Pencil}>edited</Badge>}
        <span title={`Generated with "how human" ${asset.humanize} (${humanizeLabel(asset.humanize)}). ${asset.ai_tells.length ? "AI-typical wording left: " + asset.ai_tells.join(", ") : "No AI-typical wording found."}`}>
          <Badge tone={asset.ai_tells.length ? "warning" : "success"} icon={UserCheck}>human {asset.humanize}</Badge>
        </span>
        <Badge mono>{asset.id}</Badge>
      </div>

      {asset.reply_to && (
        <div className="bc-cite-src" style={{ borderLeft: 0, borderRadius: "var(--radius-md)" }}>
          <div className="bc-label">Replying to</div>
          <blockquote style={{ whiteSpace: "pre-wrap" }}>{asset.reply_to}</blockquote>
        </div>
      )}

      {draft === null ? (
        <TextWithMarkers text={asset.text} />
      ) : (
        <div className="bc-stack" style={{ gap: 8 }}>
          <textarea className="bc-textarea" rows={Math.min(16, Math.max(4, draft.split("\n").length + 2))}
            value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="Edit text" />
          <div className="bc-row" style={{ gap: 8 }}>
            <Button size="sm" variant="success" icon={Check} loading={saving} onClick={save}>Save</Button>
            <Button size="sm" variant="ghost" icon={X} onClick={() => setDraft(null)}>Cancel</Button>
          </div>
        </div>
      )}

      {asset.ai_tells.length > 0 && draft === null && (
        <span className="bc-hint" style={{ color: "var(--warning-text)" }}>
          AI-typical wording: {asset.ai_tells.map((t) => `"${t}"`).join(", ")}. Edit it, or generate again with a higher &ldquo;how human&rdquo; setting.
        </span>
      )}

      {asset.search_query && asset.search_query !== asset.brief && (
        <span className="bc-hint">Searched the book for: {asset.search_query}</span>
      )}

      <CitationList citations={asset.citations} />

      {checks && (
        <div className="bc-stack" style={{ gap: 8 }}>
          <div className="bc-label">Verification</div>
          {checks.map((item, i) => {
            const ok = item.status === "verified";
            const Icon = ok ? Check : AlertTriangle;
            return (
              <div key={i} className="bc-check" data-ok={ok}>
                <Icon size={14} className="bc-ico" aria-hidden />
                <div>
                  {item.claim}
                  <small>{ok ? `verified · ${item.chunk_id} · sim ${item.score?.toFixed(2)}` : "not found in sources"}</small>
                </div>
              </div>
            );
          })}
        </div>
      )}
      {error && <ErrorNote>{error}</ErrorNote>}

      <div className="bc-out-f" style={{ flexWrap: "wrap" }}>
        <span>{words} words</span>
        <span style={overLimit ? { color: "var(--danger-text)", fontWeight: 600 } : undefined}
          title={limit != null ? `${platform?.label} limit: ${limit.toLocaleString()} characters (without citation markers)` : undefined}>
          · {publishable.length.toLocaleString()}{limit != null ? ` / ${limit.toLocaleString()}` : ""} chars{overLimit ? " (too long)" : ""}
        </span>
        <span>· {asset.citations.length} citations</span>
        {asset.tokens > 0 && <span>· {asset.tokens} tokens</span>}
        <span style={{ flex: 1 }} />
        <Button variant="ghost" size="sm" icon={copied ? Check : Copy} onClick={copy}
          title="Copy the text without citation markers">{copied ? "Copied" : "Copy"}</Button>
        <Button variant="ghost" size="sm" icon={Pencil} onClick={() => setDraft(asset.text)} disabled={draft !== null}>Edit</Button>
        <Button variant="ghost" size="sm" icon={ShieldCheck} loading={verifying} onClick={verify}>Verify</Button>
        <Button variant="ghost" size="sm" icon={Trash2} aria-label="Delete asset" title="Delete" onClick={remove} />
      </div>
    </article>
  );
}
