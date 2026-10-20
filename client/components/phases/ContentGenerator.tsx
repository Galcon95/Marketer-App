"use client";

import { useState, type SubmitEvent } from "react";
import { FileText, Sparkles, Wand2 } from "lucide-react";
import { api, ASSET_TYPES, errorMessage, PROJECT_ID, type AssetType } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import AssetCard from "../AssetCard";
import { Button, Card, ErrorNote, Field, Placeholder, SectionHeading } from "../ui";

/**
 * Phase 1: zero-shot generation from a brief (POST /generate with grounded: false).
 * Left: a campaign brief form. Right: all zero-shot assets of the project, newest first.
 * @param refresh Counter from AppShell; changing it reloads the asset list.
 * @param onChange Call after generating so the whole app (lists, counts) refreshes.
 */
export default function ContentGenerator({ refresh, onChange }: { refresh: number; onChange: () => void }) {
  const assets = useApi(`assets:${refresh}`, api.listAssets);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * Form submit: combine the brief fields into one sentence-like brief, e.g.
   * "Acme Pro by Acme Inc. (SaaS) <description> Audience: Developers", and request a zero-shot asset.
   * Empty optional fields are left out.
   */
  async function submit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const get = (k: string) => String(f.get(k) ?? "").trim();
    const brief = [
      get("product"),
      get("brand") && `by ${get("brand")}`,
      get("category") && `(${get("category")})`,
      get("description"),
      `Audience: ${get("audience")}`,
    ].filter(Boolean).join(" ");

    setPending(true);
    setError(null);
    try {
      await api.generate({ asset_type: get("asset_type") as AssetType, brief, grounded: false });
      onChange();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setPending(false);
    }
  }

  // The server returns assets oldest first; show only zero-shot ones, newest on top.
  const zeroShot = (assets.data ?? []).filter((a) => !a.grounded).reverse();

  return (
    <div className="bc-split">
      <Card title="Campaign brief" icon={FileText}>
        <form className="bc-stack" onSubmit={submit}>
          <Field name="product" label="Product / offer" placeholder="e.g. Acme Analytics Pro" required />
          <Field name="brand" label="Brand" placeholder="e.g. Acme Inc." />
          <Field name="category" label="Category" placeholder="e.g. B2B SaaS · analytics" />
          <Field name="description" as="textarea" label="Short description" rows={4} placeholder="What is it, who is it for, why does it matter?" />
          <Field name="audience" as="select" label="Target audience" options={["General audience", "Small businesses", "Enterprise buyers", "Developers"]} />
          <Field name="asset_type" as="select" label="Asset type" options={ASSET_TYPES} />
          <Button type="submit" icon={Sparkles} loading={pending}>{pending ? "Generating…" : "Generate (Zero-Shot)"}</Button>
          <span className="bc-hint">POST /projects/{PROJECT_ID}/generate · grounded: false</span>
          {error && <ErrorNote>{error}</ErrorNote>}
        </form>
      </Card>

      <div>
        <SectionHeading icon={Wand2} title="Generated assets" count={zeroShot.length} />
        {assets.error ? (
          <ErrorNote>{assets.error}</ErrorNote>
        ) : zeroShot.length ? (
          <div className="bc-stack">{zeroShot.map((a) => <AssetCard key={a.id} asset={a} />)}</div>
        ) : (
          <Placeholder icon={Wand2}>{assets.loading ? "Loading…" : "Nothing generated yet. Fill in the brief and press Generate."}</Placeholder>
        )}
      </div>
    </div>
  );
}
