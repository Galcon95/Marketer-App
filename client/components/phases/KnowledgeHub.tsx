"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode, type SubmitEvent } from "react";
import { Check, Database, FileText, Film, Library, Search, Sparkles, Trash2, Upload, X } from "lucide-react";
import {
  api, ASSET_TYPES, errorMessage, locationLabel, MAX_UPLOAD_BYTES, PROCESSING_STATUSES, UPLOAD_EXTENSIONS,
  type AssetType, type Chunk, type Source,
} from "@/lib/api";
import { useApi } from "@/lib/useApi";
import AssetCard from "../AssetCard";
import { Badge, Button, Card, ErrorNote, Field, Placeholder, ProgressBar, Score, SectionHeading } from "../ui";

/** Props every phase view gets from AppShell: `refresh` reloads data, `onChange` triggers a global refresh. */
type Props = { refresh: number; onChange: () => void };

/**
 * Format a byte count for display.
 * @param n Number of bytes.
 * @returns e.g. "512 B", "12.3 KB", "4.0 MB".
 */
function formatBytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
}

/**
 * Client-side check before sending; the server validates again.
 * Checks extension (UPLOAD_EXTENSIONS), maximum size and that the file is not empty.
 * @param file File picked by the user.
 * @returns An error message, or null when the file may be uploaded.
 */
function validateFile(file: File): string | null {
  const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  if (!UPLOAD_EXTENSIONS.includes(ext)) return `Unsupported file type. Allowed: ${UPLOAD_EXTENSIONS.join(", ")}`;
  if (file.size > MAX_UPLOAD_BYTES) return `File is larger than ${formatBytes(MAX_UPLOAD_BYTES)}`;
  if (file.size === 0) return "File is empty";
  return null;
}

/* ---------- Upload (+ ingestion progress, once ingestion exists) ---------- */
/**
 * Upload box: a "Choose PDF" button, the upload progress of the file being sent, and afterwards
 * the state of the created source. Shows one of three states: idle (accepted formats), sending
 * (upload percentage), or the last uploaded source (status and size).
 * @param onChange Called after a successful upload and when ingestion finishes, to refresh the app.
 */
function UploadPanel({ onChange }: { onChange: () => void }) {
  const inputRef = useRef<HTMLInputElement>(null); // hidden file input opened by the button
  const [source, setSource] = useState<Source | null>(null); // last uploaded source
  const [sending, setSending] = useState<{ name: string; size: number; percent: number } | null>(null); // upload in flight
  const [error, setError] = useState<string | null>(null);

  /**
   * Validate a file locally, then upload it with progress updates.
   * On success the new source is shown and the app refreshed; on failure the error is shown.
   * @param file The file chosen in the file dialog.
   */
  async function upload(file: File) {
    const invalid = validateFile(file);
    if (invalid) {
      setError(`${file.name}: ${invalid}`);
      return;
    }
    setError(null);
    setSource(null);
    setSending({ name: file.name, size: file.size, percent: 0 });
    try {
      setSource(await api.uploadSource(file, (percent) => setSending((s) => s && { ...s, percent })));
      onChange();
    } catch (e) {
      setError(`${file.name}: ${errorMessage(e)}`);
    } finally {
      setSending(null);
    }
  }

  // Poll GET /sources/{id} while ingestion runs (not triggered yet: uploads stop at "uploaded").
  const pollingId = source && PROCESSING_STATUSES.includes(source.status) ? source.id : null;
  useEffect(() => {
    if (!pollingId) return;
    const timer = setInterval(async () => {
      try {
        const next = await api.getSource(pollingId);
        setSource(next);
        if (next.status === "ready" || next.status === "failed") onChange();
      } catch (e) {
        setError(errorMessage(e));
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [pollingId, onChange]);

  // Pick title, badge, progress and meta line for the current state (sending / uploaded source / idle).
  let title: string;
  let badge: ReactNode = null;
  let progress: number | null = null;
  let meta: string[];
  if (sending) {
    title = sending.name;
    badge = <Badge tone="accent" dot pulse>Uploading {sending.percent}%</Badge>;
    progress = sending.percent;
    meta = [formatBytes(sending.size), "sending to server…"];
  } else if (source) {
    title = source.filename;
    badge = source.status === "ready" ? <Badge tone="success" icon={Check}>Indexed</Badge>
      : source.status === "uploaded" ? <Badge tone="success" icon={Check}>Uploaded</Badge>
      : <Badge tone="accent" dot pulse>{source.status} {source.progress}%</Badge>;
    progress = source.progress;
    meta = [formatBytes(source.size_bytes), source.id, source.status === "uploaded" ? "stored on server · not indexed yet" : `${source.chunk_count} chunks`];
  } else {
    title = "Upload a book";
    meta = [`${UPLOAD_EXTENSIONS.join(" · ").toUpperCase()} · max ${formatBytes(MAX_UPLOAD_BYTES)}`];
  }

  return (
    <div className="bc-up">
      <span className="bc-up-ico">{source?.status === "ready" ? <Database size={20} aria-hidden /> : <Upload size={20} aria-hidden />}</span>
      <div className="bc-up-main">
        <div className="bc-up-t">{title}{badge}</div>
        {progress !== null && <ProgressBar value={progress} />}
        <div className="bc-up-meta">{meta.map((m) => <span key={m}>{m}</span>)}</div>
        {error && <ErrorNote>{error}</ErrorNote>}
      </div>
      <input
        ref={inputRef}
        type="file"
        hidden
        accept={UPLOAD_EXTENSIONS.join(",")}
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = ""; // reset so choosing the same file again fires onChange
          if (file) upload(file);
        }}
      />
      <Button variant="secondary" icon={Upload} loading={sending !== null} onClick={() => inputRef.current?.click()}>
        {sending ? "Uploading…" : "Choose PDF"}
      </Button>
    </div>
  );
}

/* ---------- Sources table ---------- */
/**
 * Table of the project's sources with status, chunk count, size and per-row actions
 * (browse chunks — only for ready sources — and delete).
 * @param sources Sources to list.
 * @param error Error from loading the sources, shown instead of the table.
 * @param onBrowse Called with a source when its "Chunks" button is clicked.
 * @param onChange Called after a successful delete to refresh the app.
 */
function SourcesCard({ sources, error, onBrowse, onChange }: {
  sources: Source[]; error?: string; onBrowse: (source: Source) => void; onChange: () => void;
}) {
  const [deleteError, setDeleteError] = useState<string | null>(null);

  /**
   * Delete a source on the server (file and chunks) and refresh the app.
   * @param id Id of the source to delete.
   */
  async function remove(id: string) {
    setDeleteError(null);
    try {
      await api.deleteSource(id);
      onChange();
    } catch (e) {
      setDeleteError(errorMessage(e));
    }
  }

  return (
    <Card title="Sources" icon={Library} meta={<Badge mono>{sources.length} files</Badge>} flush>
      {error || deleteError ? (
        <div className="bc-card-body"><ErrorNote>{error ?? deleteError}</ErrorNote></div>
      ) : sources.length === 0 ? (
        <div className="bc-card-body"><Placeholder icon={Library}>No content yet. Upload a file to get started.</Placeholder></div>
      ) : (
        <div className="bc-table-wrap">
          <table className="bc-table" style={{ minWidth: 560 }}>
            <thead>
              <tr><th>File</th><th>Status</th><th>Chunks</th><th>Size</th><th /></tr>
            </thead>
            <tbody>
              {sources.map((s) => {
                const Icon = s.kind === "video" || s.kind === "audio" ? Film : FileText;
                return (
                  <tr key={s.id}>
                    <td><span className="bc-src"><Icon size={14} aria-hidden />{s.filename}</span></td>
                    <td>
                      {s.status === "ready" ? <Badge tone="success" icon={Check}>ready</Badge>
                        : s.status === "uploaded" ? <Badge icon={Check}>uploaded · not indexed</Badge>
                        : <Badge tone={s.status === "failed" ? "danger" : "accent"} dot>{s.status} {s.progress}%</Badge>}
                    </td>
                    <td className="bc-mono">{s.chunk_count}</td>
                    <td className="bc-mono">{formatBytes(s.size_bytes)}</td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      <Button variant="ghost" size="sm" icon={Database} onClick={() => onBrowse(s)} disabled={s.status !== "ready"}>Chunks</Button>
                      <Button variant="ghost" size="sm" icon={Trash2} aria-label={`Delete ${s.filename}`} onClick={() => remove(s.id)} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

/* ---------- Chunks ---------- */
/**
 * Display one chunk: id, location, token count, optional similarity score and its text.
 * @param chunk The chunk to show.
 * @param score Similarity score, shown only for search results.
 */
function ChunkCard({ chunk, score }: { chunk: Chunk; score?: number }) {
  return (
    <div className="bc-chunk" style={{ cursor: "default" }}>
      <div className="bc-chunk-h">
        <span className="bc-chunk-id">{chunk.id}</span>
        <Badge mono>{locationLabel(chunk.location)}</Badge>
        <Badge mono>{chunk.token_count} tok</Badge>
        {score != null && <Score label="sim" value={score} />}
      </div>
      <p>{chunk.text}</p>
    </div>
  );
}

/**
 * Slide-out panel listing a source's chunks: a developer view for checking ingestion.
 * Loads the first 100 chunks, focuses the close button on open, and closes on Escape
 * or a click on the backdrop.
 * @param source The source whose chunks to show.
 * @param onClose Called to close the drawer; should be stable (useCallback) to avoid re-binding keys.
 */
function SourceChunksDrawer({ source, onClose }: { source: Source; onClose: () => void }) {
  const chunks = useApi(`chunks:${source.id}`, () => api.listChunks(source.id, 0, 100));
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const page = chunks.data;
  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={`Chunks of ${source.filename}`}>
        <header className="drawer-head">
          <Database size={16} className="bc-ico" aria-hidden />
          <h3>{source.filename}</h3>
          <Badge mono>{page ? `${page.items.length} / ${page.total} chunks` : "…"}</Badge>
          <Button ref={closeRef} variant="ghost" size="sm" icon={X} aria-label="Close" onClick={onClose} />
        </header>
        <div className="drawer-body">
          <span className="bc-hint">{source.id} · {source.kind} · {formatBytes(source.size_bytes)} · GET /sources/{source.id}/chunks</span>
          {chunks.error ? (
            <ErrorNote>{chunks.error}</ErrorNote>
          ) : page?.items.length ? (
            page.items.map((c) => <ChunkCard key={c.id} chunk={c} />)
          ) : (
            <Placeholder icon={Database}>{chunks.loading ? "Loading…" : "This source has no chunks."}</Placeholder>
          )}
        </div>
      </aside>
    </>
  );
}

/* ---------- Search ---------- */
/**
 * Search box over the project's chunks. Submitting stores the query, which triggers the
 * search request through useApi; the hits are listed as ChunkCards with their scores.
 * Clearing the query (empty submit or the X button) hides the results.
 */
function ContentSearch() {
  const [query, setQuery] = useState<string | null>(null); // submitted query; null = no search
  const search = useApi(query ? `search:${query}` : null, () => api.search(query!));

  /** Form submit: read the trimmed query from the form and start the search (empty → clear). */
  function submit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    const q = String(new FormData(e.currentTarget).get("q") ?? "").trim();
    setQuery(q || null);
  }

  const hits = search.data?.hits ?? [];
  return (
    <Card title="Search your content" icon={Search} meta={query ? <Badge mono>{hits.length} hits</Badge> : undefined}>
      <div className="bc-stack">
        <form className="bc-row" style={{ flexWrap: "nowrap" }} onSubmit={submit}>
          <div style={{ flex: 1 }}><Field name="q" as="search" placeholder="e.g. Where is the main conflict introduced?" /></div>
          <Button type="submit" variant="secondary" icon={Search}>Search</Button>
          {query && <Button variant="ghost" icon={X} aria-label="Clear search" onClick={() => setQuery(null)} />}
        </form>
        {!query ? (
          <span className="bc-hint">Finds the passages in your uploaded content that best match a question or topic.</span>
        ) : search.error ? (
          <ErrorNote>{search.error}</ErrorNote>
        ) : hits.length ? (
          hits.map((h) => <ChunkCard key={h.chunk.id} chunk={h.chunk} score={h.score} />)
        ) : (
          <Placeholder icon={Search}>{search.loading ? "Searching…" : "No matches."}</Placeholder>
        )}
      </div>
    </Card>
  );
}

/* ---------- Grounded generation ---------- */
/**
 * Form for grounded (RAG) generation plus the list of grounded assets, newest first.
 * @param refresh Changing it reloads the asset list.
 * @param onChange Called after generating to refresh the app.
 */
function GroundedGenerator({ refresh, onChange }: Props) {
  const assets = useApi(`assets:${refresh}`, api.listAssets);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Form submit: request a grounded asset of the chosen type from the brief. */
  async function submit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setPending(true);
    setError(null);
    try {
      await api.generate({ asset_type: f.get("asset_type") as AssetType, brief: String(f.get("brief") ?? ""), grounded: true });
      onChange();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setPending(false);
    }
  }

  // The server returns assets oldest first; show only grounded ones, newest on top.
  const grounded = (assets.data ?? []).filter((a) => a.grounded).reverse();

  return (
    <div className="bc-stack" style={{ gap: 16 }}>
      <SectionHeading icon={Sparkles} title="Grounded asset generator" count={grounded.length} />
      <Card>
        <form className="bc-stack" onSubmit={submit}>
          <Field name="asset_type" as="select" label="Asset type" options={ASSET_TYPES} />
          <Field name="brief" as="textarea" label="Brief" rows={3} placeholder="e.g. A blurb that uses the strongest quote from the manuscript" required />
          <Button type="submit" icon={Sparkles} loading={pending}>{pending ? "Generating…" : "Generate from sources"}</Button>
          {error && <ErrorNote>{error}</ErrorNote>}
        </form>
      </Card>
      {assets.error ? (
        <ErrorNote>{assets.error}</ErrorNote>
      ) : grounded.length ? (
        grounded.map((a) => <AssetCard key={a.id} asset={a} />)
      ) : (
        <Placeholder icon={Sparkles}>{assets.loading ? "Loading…" : "Grounded assets with citations will appear here."}</Placeholder>
      )}
    </div>
  );
}

/* ---------- Phase 2 ---------- */
/**
 * Phase 2: the knowledge hub for retrieval-augmented generation. Combines upload, the sources
 * table, content search and grounded generation, and opens the chunk drawer for a source.
 * @param refresh Changing it reloads sources and assets.
 * @param onChange Called after any change (upload, delete, generate) to refresh the app.
 */
export default function KnowledgeHub({ refresh, onChange }: Props) {
  const sources = useApi(`sources:${refresh}`, api.listSources);
  const [browsing, setBrowsing] = useState<Source | null>(null); // source shown in the drawer, null = closed
  const closeDrawer = useCallback(() => setBrowsing(null), []);

  return (
    <>
      <UploadPanel onChange={onChange} />
      <SourcesCard sources={sources.data ?? []} error={sources.error} onBrowse={setBrowsing} onChange={onChange} />
      <div className="bc-split">
        <ContentSearch />
        <GroundedGenerator refresh={refresh} onChange={onChange} />
      </div>
      {browsing && <SourceChunksDrawer source={browsing} onClose={closeDrawer} />}
    </>
  );
}
