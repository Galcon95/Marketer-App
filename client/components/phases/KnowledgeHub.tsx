"use client";

import { useCallback, useEffect, useRef, useState, type SubmitEvent } from "react";
import { Check, Database, FileText, Film, Library, Search, Sparkles, Trash2, Upload, X } from "lucide-react";
import { api, ASSET_TYPES, errorMessage, locationLabel, type AssetType, type Chunk, type Source } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import AssetCard from "../AssetCard";
import { Badge, Button, Card, ErrorNote, Field, Placeholder, ProgressBar, Score, SectionHeading } from "../ui";

type Props = { refresh: number; onChange: () => void };

function formatBytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
}

/* ---------- Upload + ingestion progress ---------- */
function UploadPanel({ onChange }: { onChange: () => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [source, setSource] = useState<Source | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function upload(file: File) {
    setUploading(true);
    setError(null);
    try {
      setSource(await api.uploadSource(file));
      onChange();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setUploading(false);
    }
  }

  // Poll GET /sources/{id} until ingestion finishes.
  const pollingId = source && source.status !== "ready" && source.status !== "failed" ? source.id : null;
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

  const done = source?.status === "ready";
  return (
    <div className="bc-up">
      <span className="bc-up-ico">{done ? <Database size={20} aria-hidden /> : <Upload size={20} aria-hidden />}</span>
      <div className="bc-up-main">
        <div className="bc-up-t">
          {source?.filename ?? "Upload content to index"}
          {source && (done
            ? <Badge tone="success" icon={Check}>Indexed</Badge>
            : <Badge tone="accent" dot pulse>{source.status} {source.progress}%</Badge>)}
        </div>
        {source && <ProgressBar value={source.progress} />}
        <div className="bc-up-meta">
          {source
            ? [source.kind, formatBytes(source.size_bytes), `${source.chunk_count} chunks`, source.id].map((m) => <span key={m}>{m}</span>)
            : <span>PDF · EPUB · DOCX · TXT · MP4 · MP3 — dummy ingestion takes ~10 s</span>}
        </div>
        {error && <ErrorNote>{error}</ErrorNote>}
      </div>
      <input
        ref={inputRef}
        type="file"
        hidden
        accept=".pdf,.epub,.docx,.txt,.md,.mp4,.mov,.webm,.mp3,.wav,.m4a"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file) upload(file);
        }}
      />
      <Button variant="secondary" icon={Upload} loading={uploading} onClick={() => inputRef.current?.click()}>Upload file</Button>
    </div>
  );
}

/* ---------- Sources table ---------- */
function SourcesCard({ sources, error, onBrowse, onChange }: {
  sources: Source[]; error?: string; onBrowse: (source: Source) => void; onChange: () => void;
}) {
  const [deleteError, setDeleteError] = useState<string | null>(null);

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
                      {s.status === "ready"
                        ? <Badge tone="success" icon={Check}>ready</Badge>
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

/** Slide-out panel listing a source's chunks: a developer view for checking ingestion. */
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
function ContentSearch() {
  const [query, setQuery] = useState<string | null>(null);
  const search = useApi(query ? `search:${query}` : null, () => api.search(query!));

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
function GroundedGenerator({ refresh, onChange }: Props) {
  const assets = useApi(`assets:${refresh}`, api.listAssets);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
export default function KnowledgeHub({ refresh, onChange }: Props) {
  const sources = useApi(`sources:${refresh}`, api.listSources);
  const [browsing, setBrowsing] = useState<Source | null>(null);
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
