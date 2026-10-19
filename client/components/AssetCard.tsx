"use client";

import { useState } from "react";
import { AlertTriangle, Check, ShieldCheck, Sparkles } from "lucide-react";
import { api, assetTypeLabel, errorMessage, locationLabel, type Asset, type VerifyItem } from "@/lib/api";
import { Badge, Button, ErrorNote, Score } from "./ui";

/** A generated asset with its citations and an on-demand verification (POST /verify). */
export default function AssetCard({ asset }: { asset: Asset }) {
  const [checks, setChecks] = useState<VerifyItem[] | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const words = asset.text.trim().split(/\s+/).filter(Boolean).length;

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

      <p>{asset.text}</p>

      {asset.citations.length > 0 && (
        <div className="bc-stack" style={{ gap: 8 }}>
          <div className="bc-label">Retrieved sources</div>
          {asset.citations.map((c) => (
            <div key={c.chunk_id} className="bc-cite-src" style={{ borderLeft: 0, borderRadius: "var(--radius-md)" }}>
              <div className="bc-cite-k">
                <Badge mono>{locationLabel(c.location)}</Badge>
                <Badge mono>{c.chunk_id}</Badge>
                <Score label="sim" value={c.score} />
              </div>
              <blockquote>{c.quote}</blockquote>
            </div>
          ))}
        </div>
      )}

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
        <span style={{ flex: 1 }} />
        <Button variant="ghost" size="sm" icon={ShieldCheck} loading={verifying} onClick={verify}>Verify</Button>
      </div>
    </article>
  );
}
