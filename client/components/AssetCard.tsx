"use client";

import { useState } from "react";
import { AlertTriangle, Check, ShieldCheck, Sparkles } from "lucide-react";
import { api, assetTypeLabel, errorMessage, locationLabel, type Asset, type Citation, type VerifyItem } from "@/lib/api";
import { Badge, Button, ErrorNote, Score } from "./ui";

/**
 * Numbered list of cited passages ([1], [2], ... matching the markers in a generated text), each
 * with its location, chunk id, similarity and quote. Renders nothing if there are no citations.
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
            <Badge mono>{locationLabel(c.location)}</Badge>
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
 * A generated asset with its citations and an on-demand verification (POST /verify).
 * Shows the asset text, its cited sources (if grounded; numbered like the [n] markers in the
 * text), a word/citation count, and a
 * Verify button that checks each sentence against the project's sources and lists the results.
 * @param asset The asset to display.
 */
export default function AssetCard({ asset }: { asset: Asset }) {
  const [checks, setChecks] = useState<VerifyItem[] | null>(null); // null until Verify was pressed
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const words = asset.text.trim().split(/\s+/).filter(Boolean).length;

  /** Send the asset text to POST /verify and store the per-claim results (or the error). */
  async function verify() {
    setVerifying(true);
    setError(null);
    try {
      setChecks((await api.verify(asset.text)).items);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setVerifying(false);
    }
  }

  return (
    <article className="bc-out">
      <div className="bc-out-h">
        <strong>{assetTypeLabel(asset.asset_type)}</strong>
        {asset.grounded
          ? <Badge tone="success" icon={ShieldCheck}>Grounded</Badge>
          : <Badge icon={Sparkles}>Zero-shot</Badge>}
        <Badge mono>{asset.id}</Badge>
      </div>

      {/* pre-wrap keeps the line breaks of multi-line assets (newsletter, ad variants, persona). */}
      <p style={{ whiteSpace: "pre-wrap" }}>{asset.text}</p>

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

      <div className="bc-out-f">
        <span>{words} words</span>
        <span>· {asset.citations.length} citations</span>
        {asset.tokens > 0 && <span>· {asset.tokens} tokens</span>}
        <span style={{ flex: 1 }} />
        <Button variant="ghost" size="sm" icon={ShieldCheck} loading={verifying} onClick={verify}>Verify</Button>
      </div>
    </article>
  );
}
