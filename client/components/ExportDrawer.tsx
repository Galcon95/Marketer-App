"use client";

/**
 * The Export panel (top bar "Export"): download the generated assets as CSV (for a planning sheet or a scheduling
 * tool) or Markdown (to read and edit), all of them or only one book and/or one asset type
 * (GET /projects/{id}/assets/export).
 */

import { useState, type SubmitEvent } from "react";
import { Download, FileText } from "lucide-react";
import { api, ASSET_TYPES, ASSET_GROUPS, bookTitle, downloadAssets, errorMessage, type AssetType, type ExportFormat } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { Button, Drawer, ErrorNote, Field, Segmented } from "./ui";

const ALL = "";

const FORMATS: { value: ExportFormat; label: string }[] = [
  { value: "csv", label: "CSV" },
  { value: "csv_semicolon", label: "CSV for Excel" },
  { value: "md", label: "Markdown" },
];

/**
 * Drawer with the export choices and a Download button.
 * @param onClose Close the drawer.
 */
export default function ExportDrawer({ onClose }: { onClose: () => void }) {
  const sources = useApi("export-books", api.listSources);
  const books = (sources.data ?? []).filter((s) => s.status === "ready" && s.kind === "document");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  /** Form submit: download the file with the chosen book, type and format. */
  async function submit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const get = (k: string) => String(f.get(k) ?? "");
    setPending(true);
    setError(null);
    setSaved(null);
    try {
      setSaved(await downloadAssets(get("format") as ExportFormat, {
        asset_type: (get("asset_type") || undefined) as AssetType | undefined,
        source_id: get("book") || undefined,
      }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <Drawer icon={FileText} title="Export assets" label="Download your generated assets as a file" onClose={onClose}>
      <form className="bc-stack" onSubmit={submit}>
        <span className="bc-hint">
          Download your posts, blurbs, campaigns and other assets, newest first. CSV opens in Google Sheets or Excel
          and can be imported into scheduling tools; Markdown is easy to read and edit.
        </span>
        <Field name="book" as="select" label="Book"
          options={[{ value: ALL, label: "All books" }, ...books.map((b) => ({ value: b.id, label: bookTitle(b.filename) }))]} />
        <Field name="asset_type" as="select" label="Asset type"
          groups={[{ label: "All", options: [{ value: ALL, label: "All types" }] },
            ...ASSET_GROUPS.map((g) => ({ label: g, options: ASSET_TYPES.filter((t) => t.group === g) }))]} />
        <Segmented name="format" label="Format" options={FORMATS} defaultValue="csv" />
        <span className="bc-hint">
          CSV: one row per asset, the text ready to post (without the [1] markers), its sources in their own column.
          CSV for Excel uses semicolons, which Excel with German settings needs. Markdown keeps the markers and lists
          the sources under each text.
        </span>
        <div className="bc-studio-actions">
          <Button type="submit" icon={Download} loading={pending}>{pending ? "Preparing…" : "Download"}</Button>
        </div>
        {saved && <span className="bc-hint">Saved as {saved} (in your downloads folder).</span>}
        {error && <ErrorNote>{error}</ErrorNote>}
      </form>
    </Drawer>
  );
}
