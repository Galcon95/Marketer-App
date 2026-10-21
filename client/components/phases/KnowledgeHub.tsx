"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode, type SubmitEvent } from "react";
import { AlertTriangle, BookOpen, Check, ChevronDown, Database, FileText, Film, Library, MessageSquare, Play, RotateCcw, Sparkles, Target, Trash2, Upload, X } from "lucide-react";
import {
  api, ASSET_TYPES, bookTitle, errorMessage, humanizeLabel, LENGTHS, locationLabel, MAX_UPLOAD_BYTES, PLATFORMS, PROCESSING_STATUSES,
  TONES, UPLOAD_EXTENSIONS, usesPlatform,
  type AssetType, type BookSummary, type Chunk, type ChunkPage, type Length, type Platform, type Source, type Tone,
} from "@/lib/api";
import { useApi } from "@/lib/useApi";
import AssetCard, { CitationList } from "../AssetCard";
import BookCover, { PageLink } from "../BookCover";
import { Badge, Button, Card, Drawer, ErrorNote, Field, Placeholder, ProgressBar, RangeField, Score, SectionHeading } from "../ui";

/** Props every phase view gets from AppShell: `refresh` reloads data, `onChange` triggers a global refresh. */
type Props = { refresh: number; onChange: () => void };

/** Which side panel is open for a source: its chunks or its book summary. */
type DrawerView = "chunks" | "summary";

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

/* ---------- Upload + ingestion progress ---------- */
/**
 * Upload box: a "Choose PDF" button, the upload progress of the file being sent, and afterwards
 * the processing state of the created source. Shows one of three states: idle (accepted formats),
 * sending (upload percentage), or the last uploaded source (status, progress, chunks or error).
 * The source's live status comes from the sources list, which KnowledgeHub refreshes while processing.
 * @param sources Current sources of the project.
 * @param sourcesLoading True while the sources list is being reloaded.
 * @param onChange Called after a successful upload to refresh the app.
 */
function UploadPanel({ sources, sourcesLoading, onChange }: { sources: Source[]; sourcesLoading: boolean; onChange: () => void }) {
  const inputRef = useRef<HTMLInputElement>(null); // hidden file input opened by the button
  const [uploaded, setUploaded] = useState<Source | null>(null); // upload response of the last file
  const [sending, setSending] = useState<{ name: string; size: number; percent: number } | null>(null); // upload in flight
  const [error, setError] = useState<string | null>(null);
  // Latest state of the uploaded source. The upload response bridges the gap until the reloaded
  // list contains it; once the list is loaded without it (deleted), the panel returns to idle.
  const source = uploaded && (sources.find((s) => s.id === uploaded.id) ?? (sourcesLoading ? uploaded : null));

  /**
   * Validate a file locally, then upload it with progress updates.
   * On success the new source is shown and the app refreshed (the server starts processing it
   * right away); on failure the error is shown.
   * @param file The file chosen in the file dialog.
   */
  async function upload(file: File) {
    const invalid = validateFile(file);
    if (invalid) {
      setError(`${file.name}: ${invalid}`);
      return;
    }
    setError(null);
    setUploaded(null);
    setSending({ name: file.name, size: file.size, percent: 0 });

    try {
      setUploaded(await api.uploadSource(file, (percent) => setSending((s) => s && { ...s, percent })));
      onChange();
    } catch (e) {
      setError(`${file.name}: ${errorMessage(e)}`);
    } finally {
      setSending(null);
    }
  }

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
    badge = <SourceStatusBadge source={source} />;
    progress = source.status === "failed" ? null : source.progress;
    meta = [formatBytes(source.size_bytes), source.id,
      source.status === "ready" ? `${source.chunk_count} chunks` : source.status === "failed" ? "processing failed" : "processing…"];
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
        {!sending && source?.error && <ErrorNote>{source.error}</ErrorNote>}
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

/* ---------- Book shelf ---------- */
/**
 * Shortened text: whole sentences up to about `max` characters, with "…" if something was left out.
 * @param text Text to shorten.
 * @param max Rough character budget.
 */
function firstSentences(text: string, max: number) {
  const sentences = text.replace(/\s+/g, " ").match(/[^.!?]+[.!?]+["”’]?/g) ?? [text];
  let out = "";
  for (const sentence of sentences) {
    if (out && (out + sentence).length > max) return `${out.trim()} …`;
    out += sentence;
  }
  return out.trim();
}

/**
 * "Your books": one card per processed book (cover, title, stats, a summary teaser and key themes),
 * the visual overview at the top of the Knowledge Hub. Hidden until a book is processed.
 * @param books The processed books (see readyBooks).
 * @param refresh Changing it reloads the summaries (e.g. after one was created).
 * @param selected Id of the book being worked on, or null for all books.
 * @param onSelect Called with a book's id (or null to clear) when "Work on this book" is clicked.
 * @param onBrowse Opens the summary or chunks panel of a book.
 */
function BookShelf({ books, refresh, selected, onSelect, onBrowse }: {
  books: Source[]; refresh: number; selected: string | null;
  onSelect: (id: string | null) => void; onBrowse: (source: Source, view: DrawerView) => void;
}) {
  if (books.length === 0) return null;
  return (
    <div>
      <SectionHeading icon={Library} title="Your books" count={books.length} />
      <div className="bc-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(420px, 100%), 1fr))" }}>
        {books.map((book) => (
          <BookCard key={book.id} source={book} refresh={refresh} selected={selected === book.id}
            onSelect={() => onSelect(selected === book.id ? null : book.id)} onBrowse={onBrowse} />
        ))}
      </div>
    </div>
  );
}

/** The processed books of a project (ready PDFs and other documents), in upload order. */
function readyBooks(sources: Source[]) {
  return sources.filter((s) => s.status === "ready" && s.kind === "document");
}

/**
 * "Working on" bar above Ask and Generate: choose one book or all books. Ask your book, the
 * generator and the generated-assets list then only use that book.
 * @param books The processed books.
 * @param selected Id of the selected book, or null for all books.
 * @param onSelect Called with the chosen book's id, or null for all books.
 */
function BookPicker({ books, selected, onSelect }: { books: Source[]; selected: string | null; onSelect: (id: string | null) => void }) {
  if (books.length === 0) return null;
  const book = books.find((b) => b.id === selected);
  return (
    <div className="bc-card" style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 16px", flexWrap: "wrap" }}>
      {book ? <BookCover sourceId={book.id} title={bookTitle(book.filename)} width={26} link /> : <Library size={18} className="bc-ico" aria-hidden />}
      <strong>Working on</strong>
      <div className="bc-select-wrap" style={{ minWidth: 260, flex: "0 1 420px" }}>
        <select className="bc-select" aria-label="Book to work on" value={selected ?? ""} onChange={(e) => onSelect(e.target.value || null)}>
          <option value="">All books ({books.length})</option>
          {books.map((b) => <option key={b.id} value={b.id}>{bookTitle(b.filename)}</option>)}
        </select>
        <ChevronDown size={16} className="bc-ico" aria-hidden />
      </div>
      <span className="bc-hint">Ask your book, the generator and the asset list use {book ? "only this book" : "all books"}.</span>
    </div>
  );
}

/**
 * One book on the shelf: cover (click: opens the PDF), title, chunk/chapter/size badges, the first sentences of its summary
 * and up to four key themes, with buttons to open the summary (or create it) and the chunks.
 * The book being worked on is highlighted with an accent border.
 * @param source The book.
 * @param refresh Changing it reloads the summary.
 * @param selected True if this is the book being worked on.
 * @param onSelect Toggles this book as the one being worked on.
 * @param onBrowse Opens the summary or chunks panel.
 */
function BookCard({ source, refresh, selected, onSelect, onBrowse }: {
  source: Source; refresh: number; selected: boolean; onSelect: () => void; onBrowse: (source: Source, view: DrawerView) => void;
}) {
  const summary = useApi(`book-summary:${source.id}:${refresh}`, () => api.getSummary(source.id));
  const s = summary.data;
  const title = bookTitle(source.filename);
  return (
    <Card className={selected ? "book-selected" : undefined}>
      <div style={{ display: "flex", gap: 20, alignItems: "flex-start" }}>
        <BookCover sourceId={source.id} title={title} width={120} link />
        <div className="bc-stack" style={{ gap: 10, minWidth: 0, flex: 1 }}>
          <h3 style={{ margin: 0, fontSize: 18, lineHeight: 1.3 }}>{title}</h3>
          <div className="bc-row" style={{ gap: 6 }}>
            <Badge tone="success" icon={Check}>ready</Badge>
            <Badge mono>{source.chunk_count} chunks</Badge>
            {s && <Badge mono>{s.chapters.length} chapters</Badge>}
            <Badge mono>{formatBytes(source.size_bytes)}</Badge>
          </div>
          {s ? (
            <p style={{ margin: 0, color: "var(--ink-muted)" }}>{firstSentences(s.summary, 260)}</p>
          ) : !summary.loading && (
            <span className="bc-hint">No summary yet. Create one to see what the book is about at a glance.</span>
          )}
          {s && (
            <div className="bc-row" style={{ gap: 6 }}>
              {s.themes.slice(0, 4).map((theme) => <Badge key={theme} tone="accent">{theme}</Badge>)}
            </div>
          )}
          <div className="bc-row" style={{ gap: 8 }}>
            <Button size="sm" variant={s ? "secondary" : "success"} icon={BookOpen} onClick={() => onBrowse(source, "summary")}>
              {s ? "Summary" : "Create summary"}
            </Button>
            <Button size="sm" variant="ghost" icon={Database} onClick={() => onBrowse(source, "chunks")}>Chunks</Button>
            <Button size="sm" variant={selected ? "primary" : "ghost"} icon={selected ? Check : Target} onClick={onSelect}
              title={selected ? "Stop working on only this book" : "Ask and generate for this book only"}>
              {selected ? "Working on this book" : "Work on this book"}
            </Button>
          </div>
        </div>
      </div>
    </Card>
  );
}

/* ---------- Sources table ---------- */
/** True while the server is processing a source (queued … embedding). */
function isProcessing(source: Source) {
  return PROCESSING_STATUSES.includes(source.status);
}

/**
 * Status badge of a source: "ready", "uploaded · not indexed", "failed" (error as tooltip),
 * or the running step with its progress, e.g. "chunking 40%".
 * @param source The source whose status to show.
 */
function SourceStatusBadge({ source }: { source: Source }) {
  if (source.status === "ready") return <Badge tone="success" icon={Check}>ready</Badge>;
  if (source.status === "uploaded") return <Badge icon={Check}>uploaded · not indexed</Badge>;
  if (source.status === "failed") return <span title={source.error ?? undefined}><Badge tone="danger" icon={AlertTriangle}>failed</Badge></span>;
  return <Badge tone="accent" dot pulse>{source.status} {source.progress}%</Badge>;
}

/**
 * Per-row button that starts processing a source; its label depends on the status:
 * "Process" (uploaded, never processed), "Re-index" (ready), "Retry" (failed), and a disabled
 * spinner while processing.
 * @param source The source of the row.
 * @param starting True while the start request is being sent.
 * @param onStart Called when the button is clicked.
 */
function IngestButton({ source, starting, onStart }: { source: Source; starting: boolean; onStart: () => void }) {
  if (isProcessing(source) || starting) return <Button variant="ghost" size="sm" loading>Processing</Button>;
  const [label, icon, hint] = source.status === "uploaded" ? ["Process", Play, "Split the PDF into chunks and embed them for search"]
    : source.status === "failed" ? ["Retry", RotateCcw, "Run the processing again"]
    : ["Re-index", RotateCcw, "Rebuild the chunks and vectors from the PDF (e.g. after changing chunk settings or the embedding model)"];
  return <Button variant="ghost" size="sm" icon={icon} title={hint} onClick={onStart}>{label}</Button>;
}

/**
 * Table of the project's sources with status, chunk count, size and per-row actions
 * (process / re-index / retry, summary and chunks — only for ready sources — and delete).
 * @param sources Sources to list.
 * @param error Error from loading the sources, shown instead of the table.
 * @param onBrowse Called with a source and the panel to open when its "Summary" or "Chunks" button is clicked.
 * @param onChange Called after a successful action to refresh the app.
 */
function SourcesCard({ sources, error, onBrowse, onChange }: {
  sources: Source[]; error?: string; onBrowse: (source: Source, view: DrawerView) => void; onChange: () => void;
}) {
  const [actionError, setActionError] = useState<string | null>(null);
  const [starting, setStarting] = useState<string | null>(null); // id of the source whose processing is being started

  /**
   * Delete a source on the server (file and chunks) and refresh the app.
   * @param id Id of the source to delete.
   */
  async function remove(id: string) {
    setActionError(null);
    try {
      await api.deleteSource(id);
      onChange();
    } catch (e) {
      setActionError(errorMessage(e));
    }
  }

  /**
   * Ask the server to (re)build a source's chunks, then refresh so the row shows "queued"
   * (KnowledgeHub keeps refreshing the list until processing ends).
   * @param id Id of the source to process.
   */
  async function ingest(id: string) {
    setActionError(null);
    setStarting(id);
    try {
      await api.ingestSource(id);
      onChange();
    } catch (e) {
      setActionError(errorMessage(e));
    } finally {
      setStarting(null);
    }
  }

  return (
    <Card title="Sources" icon={Library} meta={<Badge mono>{sources.length} files</Badge>} flush>
      {actionError && <div className="bc-card-body"><ErrorNote>{actionError}</ErrorNote></div>}
      {error ? (
        <div className="bc-card-body"><ErrorNote>{error}</ErrorNote></div>
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
                    <td>
                      <span className="bc-src">
                        {s.kind === "document" && s.status === "ready"
                          ? <BookCover sourceId={s.id} title={bookTitle(s.filename)} width={22} link />
                          : <Icon size={14} aria-hidden />}
                        {s.filename}
                      </span>
                    </td>
                    <td><SourceStatusBadge source={s} /></td>
                    <td className="bc-mono">{s.chunk_count}</td>
                    <td className="bc-mono">{formatBytes(s.size_bytes)}</td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      <IngestButton source={s} starting={starting === s.id} onStart={() => ingest(s.id)} />
                      <Button variant="ghost" size="sm" icon={BookOpen} onClick={() => onBrowse(s, "summary")} disabled={s.status !== "ready"}
                        title="What the book is about: overview, key themes and chapter summaries">Summary</Button>
                      <Button variant="ghost" size="sm" icon={Database} onClick={() => onBrowse(s, "chunks")} disabled={s.status !== "ready"}>Chunks</Button>
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
 * Display one chunk: id, location (click: opens the PDF at that page), token count, optional similarity score and its text.
 * @param chunk The chunk to show.
 * @param score Similarity score, shown only for search results.
 */
function ChunkCard({ chunk, score }: { chunk: Chunk; score?: number }) {
  return (
    <div className="bc-chunk" style={{ cursor: "default" }}>
      <div className="bc-chunk-h">
        <span className="bc-chunk-id">{chunk.id}</span>
        <PageLink sourceId={chunk.source_id} page={chunk.location.page}><Badge mono>{locationLabel(chunk.location)}</Badge></PageLink>
        <Badge mono>{chunk.token_count} tok</Badge>
        {score != null && <Score label="sim" value={score} />}
      </div>
      <p>{chunk.text}</p>
    </div>
  );
}

/**
 * Load every chunk of a source by requesting pages of 100 until the total is reached.
 * @param sourceId Source whose chunks to load.
 * @returns One ChunkPage holding all chunks.
 */
async function listAllChunks(sourceId: string): Promise<ChunkPage> {
  const first = await api.listChunks(sourceId, 0, 100);
  const items = [...first.items];
  while (items.length < first.total) {
    const next = await api.listChunks(sourceId, items.length, 100);
    if (next.items.length === 0) break;
    items.push(...next.items);
  }
  return { ...first, items, limit: items.length };
}

/**
 * Slide-out panel listing a source's chunks: a developer view for checking ingestion.
 * Loads all chunks (page by page).
 * @param source The source whose chunks to show.
 * @param onClose Called to close the drawer.
 */
function SourceChunksDrawer({ source, onClose }: { source: Source; onClose: () => void }) {
  const chunks = useApi(`chunks:${source.id}`, () => listAllChunks(source.id));
  const page = chunks.data;
  return (
    <Drawer icon={Database} title={source.filename} label={`Chunks of ${source.filename}`} onClose={onClose}
      meta={<Badge mono>{page ? `${page.items.length} / ${page.total} chunks` : "…"}</Badge>}>
      <span className="bc-hint">{source.id} · {source.kind} · {formatBytes(source.size_bytes)} · GET /sources/{source.id}/chunks</span>
      {chunks.error ? (
        <ErrorNote>{chunks.error}</ErrorNote>
      ) : page?.items.length ? (
        page.items.map((c) => <ChunkCard key={c.id} chunk={c} />)
      ) : (
        <Placeholder icon={Database}>{chunks.loading ? "Loading…" : "This source has no chunks."}</Placeholder>
      )}
    </Drawer>
  );
}

/**
 * Page range for display, e.g. "pp. 13–15", "p. 9", or "" if unknown.
 * @param first First page of the range.
 * @param last Last page of the range.
 */
function pagesLabel(first: number | null, last: number | null) {
  if (first == null) return "";
  return last == null || last === first ? `p. ${first}` : `pp. ${first}–${last}`;
}

/**
 * Slide-out panel with a book's summary: what the book is about, key themes and a short summary
 * per chapter. If none exists yet, offers to create it (the server reads the whole book: each
 * chapter is summarized, then combined); an existing summary can be regenerated.
 * @param source The book (a ready source).
 * @param onClose Called to close the drawer.
 * @param onChange Called after a summary was created, to refresh token counts.
 */
function SummaryDrawer({ source, onClose, onChange }: { source: Source; onClose: () => void; onChange: () => void }) {
  const loaded = useApi(`summary:${source.id}`, () => api.getSummary(source.id));
  const [created, setCreated] = useState<BookSummary | null>(null); // summary created in this panel
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const summary = created ?? loaded.data ?? null;

  /** Ask the server to create (or recreate) the summary; shows it when done. */
  async function create() {
    setCreating(true);
    setError(null);
    try {
      setCreated(await api.createSummary(source.id));
      onChange();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setCreating(false);
    }
  }

  return (
    <Drawer icon={BookOpen} title={bookTitle(source.filename)} label={`Summary of ${source.filename}`} onClose={onClose}
      meta={summary ? <Badge mono>{summary.chapters.length} chapters</Badge> : undefined}>
      {loaded.error ? (
        <ErrorNote>{loaded.error}</ErrorNote>
      ) : !summary ? (
        loaded.loading ? (
          <Placeholder icon={BookOpen}>Loading…</Placeholder>
        ) : (
          <div className="bc-stack">
            <Placeholder icon={BookOpen}>
              No summary yet. Creating one reads the whole book: every chapter is summarized, then the
              chapter summaries are combined into an overview with key themes (about 10–40 seconds).
            </Placeholder>
            <Button icon={Sparkles} loading={creating} onClick={create}>{creating ? "Summarizing the book…" : "Create summary"}</Button>
          </div>
        )
      ) : (
        <>
          <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
            <BookCover sourceId={source.id} title={bookTitle(source.filename)} width={96} link />
            <div className="bc-stack" style={{ gap: 8, minWidth: 0 }}>
              <div className="bc-label">What the book is about</div>
              {summary.summary.split(/\n\s*\n/).map((paragraph, i) => <p key={i} style={{ margin: 0 }}>{paragraph}</p>)}
            </div>
          </div>
          <div className="bc-label">Key themes</div>
          <div className="bc-row" style={{ gap: 6 }}>
            {summary.themes.map((theme) => <Badge key={theme} tone="accent">{theme}</Badge>)}
          </div>
          <div className="bc-label">Chapters</div>
          {summary.chapters.map((ch, i) => (
            <div key={i} className="bc-chunk" style={{ cursor: "default" }}>
              <div className="bc-chunk-h">
                <strong>{ch.chapter ?? "Front matter"}</strong>
                {ch.first_page != null && <Badge mono>{pagesLabel(ch.first_page, ch.last_page)}</Badge>}
              </div>
              <p>{ch.summary}</p>
            </div>
          ))}
          <div className="bc-row" style={{ alignItems: "center" }}>
            <span className="bc-hint" style={{ flex: 1 }}>
              {summary.model} · {summary.tokens.toLocaleString()} tokens · {new Date(summary.created_at).toLocaleString()}
            </span>
            <Button variant="success" size="sm" icon={RotateCcw} loading={creating} onClick={create}
              title="Summarize the book again (costs tokens; the saved summary is replaced)">Regenerate</Button>
          </div>
        </>
      )}
      {error && <ErrorNote>{error}</ErrorNote>}
    </Drawer>
  );
}

/* ---------- Ask your book ---------- */
/**
 * "Ask your book", NotebookLM-style: a question is answered by the LLM from the most relevant
 * passages of the project's books (POST /ask). Shows the answer with [n] markers, the cited
 * passages numbered to match, and — collapsed — all retrieved passages with their scores, so the
 * evidence can be checked. Submitting stores the question, which triggers the request through
 * useApi; clearing it (empty submit or the X button) hides the result.
 * @param bookId Only use this book; null = all books.
 * @param onChange Called after each answer, so the usage totals in the top bar update.
 */
function AskBook({ bookId, onChange }: { bookId: string | null; onChange: () => void }) {
  const [question, setQuestion] = useState<string | null>(null); // submitted question; null = nothing asked
  const ask = useApi(question ? `ask:${bookId ?? "all"}:${question}` : null,
    () => api.ask(question!, 6, bookId ? [bookId] : undefined));
  const answered = ask.data;
  useEffect(() => {
    if (answered) onChange();
  }, [answered, onChange]);

  /** Form submit: read the trimmed question from the form and ask it (empty → clear). */
  function submit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    const q = String(new FormData(e.currentTarget).get("q") ?? "").trim();
    setQuestion(q || null);
  }

  const result = ask.loading ? undefined : ask.data; // hide the previous answer while a new one loads
  return (
    <Card title="Ask your book" icon={MessageSquare} meta={result ? <Badge mono>{result.tokens} tokens</Badge> : undefined}>
      <div className="bc-stack">
        <form className="bc-row" style={{ flexWrap: "nowrap" }} onSubmit={submit}>
          <div style={{ flex: 1 }}><Field name="q" as="search" placeholder="e.g. How will Garden City be financed?" /></div>
          <Button type="submit" variant="secondary" icon={Sparkles} loading={ask.loading}>Ask</Button>
          {question && <Button variant="ghost" icon={X} aria-label="Clear question" onClick={() => setQuestion(null)} />}
        </form>
        {!question ? (
          <span className="bc-hint">
            Ask anything about your uploaded books. The answer is written only from the most relevant
            passages, with numbered citations; if the books don&apos;t cover it, it says so.
          </span>
        ) : ask.error ? (
          <ErrorNote>{ask.error}</ErrorNote>
        ) : !result ? (
          <Placeholder icon={MessageSquare}>Reading the relevant passages…</Placeholder>
        ) : (
          <>
            <p style={{ whiteSpace: "pre-wrap", margin: 0 }}>{result.answer}</p>
            <CitationList citations={result.citations} />
            <details>
              <summary className="bc-hint" style={{ cursor: "pointer" }}>All retrieved passages ({result.passages.length})</summary>
              <div className="bc-stack" style={{ marginTop: 8 }}>
                {result.passages.map((h) => <ChunkCard key={h.chunk.id} chunk={h.chunk} score={h.score} />)}
              </div>
            </details>
          </>
        )}
      </div>
    </Card>
  );
}

/* ---------- Grounded generation ---------- */
/** Example brief per asset type, shown as the brief's placeholder (for replies: the optional angle). */
const BRIEF_EXAMPLES: Record<AssetType, string> = {
  blurb: "e.g. Why this book still matters today; use the strongest quote",
  social_post: "e.g. Make people curious about the book's central idea, with a short quote",
  social_reply: "e.g. Agree partly, but add the book's view that both sides can be combined",
  video_script: "e.g. Why this old book still answers today's problem; end with a question to comment on",
  youtube_video: "e.g. A 8-minute video explaining the book's central idea for beginners",
  newsletter: "e.g. Introduce the book to readers interested in housing and city life; call to action: read chapter I",
  ad_copy: "e.g. Ads for people frustrated with expensive city rents",
  lead_magnet: "e.g. A free guide with 5 ideas from the book for better neighbourhoods",
  persona: "e.g. The ideal reader of this book among today's professionals",
};

/**
 * Form for grounded (RAG) generation plus the list of grounded assets, newest first.
 * Options adapt to the asset type: social posts, replies and video scripts choose a platform (which
 * decides length and style), other types a length; replies take the post to answer plus an optional
 * angle, all other types a brief (with an example that fits the type). With a book selected, it
 * generates from that book only and lists only that book's assets.
 * @param refresh Changing it reloads the asset list.
 * @param bookId Only use (and list assets of) this book; null = all books.
 * @param onChange Called after generating (and after editing or deleting an asset) to refresh the app.
 */
function GroundedGenerator({ refresh, bookId, onChange }: Props & { bookId: string | null }) {
  const assets = useApi(`assets:${refresh}`, api.listAssets);
  const [assetType, setAssetType] = useState<AssetType>("blurb"); // decides which fields are shown
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isReply = assetType === "social_reply";

  /** Form submit: request a grounded asset with the chosen type, options and brief (or post + angle). */
  async function submit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const get = (k: string) => String(f.get(k) ?? "").trim();
    setPending(true);
    setError(null);
    try {
      await api.generate({
        asset_type: assetType,
        brief: get("brief"),
        grounded: true,
        tone: (get("tone") || "neutral") as Tone,
        audience: get("audience"),
        humanize: Number(get("humanize") || 60),
        ...(bookId ? { source_ids: [bookId] } : {}),
        ...(usesPlatform(assetType) ? { platform: get("platform") as Platform } : { length: get("length") as Length }),
        ...(isReply ? { reply_to: get("reply_to") } : {}),
      });
      onChange();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setPending(false);
    }
  }

  // The server returns assets oldest first; show only grounded ones (of the selected book), newest on top.
  const grounded = (assets.data ?? [])
    .filter((a) => a.grounded && (!bookId || a.source_ids.includes(bookId)))
    .reverse();

  return (
    <div className="bc-stack" style={{ gap: 16 }}>
      <SectionHeading icon={Sparkles} title="Grounded asset generator" count={grounded.length} />
      <Card>
        <form className="bc-stack" onSubmit={submit}>
          <Field name="asset_type" as="select" label="Asset type" options={ASSET_TYPES}
            onChange={(value) => setAssetType(value as AssetType)} />
          <div className="bc-row" style={{ gap: 12, alignItems: "flex-start" }}>
            <div style={{ flex: 1, minWidth: 140 }}>
              {usesPlatform(assetType)
                ? <Field name="platform" as="select" label="Platform" options={PLATFORMS} />
                : <Field name="length" as="select" label="Length" options={LENGTHS} defaultValue="standard" />}
            </div>
            <div style={{ flex: 1, minWidth: 140 }}>
              <Field name="tone" as="select" label="Tone" options={TONES} />
            </div>
          </div>
          <Field name="audience" label="Target audience (optional)" placeholder="e.g. young urban planners" />
          <RangeField name="humanize" label="How human should it sound?" defaultValue={60} describe={humanizeLabel}
            hint="Higher = less typical AI wording. From 60 on, AI clichés found in the result are rewritten automatically." />
          {isReply && (
            <Field name="reply_to" as="textarea" label="Their post" rows={5} required
              placeholder="Paste the post you want to reply to" />
          )}
          <Field name="brief" as="textarea" label={isReply ? "Your angle (optional)" : "Brief"} rows={3}
            placeholder={BRIEF_EXAMPLES[assetType]} required={!isReply} />
          <Button type="submit" icon={Sparkles} loading={pending}>
            {pending ? "Generating…" : isReply ? "Generate reply from sources" : "Generate from sources"}
          </Button>
          {error && <ErrorNote>{error}</ErrorNote>}
        </form>
      </Card>
      {assets.error ? (
        <ErrorNote>{assets.error}</ErrorNote>
      ) : grounded.length ? (
        grounded.map((a) => <AssetCard key={a.id} asset={a} onChange={onChange} />)
      ) : (
        <Placeholder icon={Sparkles}>{assets.loading ? "Loading…" : "Grounded assets with citations will appear here."}</Placeholder>
      )}
    </div>
  );
}

/* ---------- Phase 1 ---------- */
/**
 * Phase 1: the knowledge hub for retrieval-augmented generation. Combines upload, the book shelf, the sources
 * table, "Ask your book" (questions answered from the books) and grounded generation, and opens the chunk drawer for a source.
 * While any source is being processed, the sources list is reloaded every second so the upload
 * panel and the table show live progress; when processing ends, the whole app is refreshed once
 * (sidebar counts, project stats).
 * @param refresh Changing it reloads sources and assets.
 * @param onChange Called after any change (upload, delete, generate) to refresh the app.
 */
export default function KnowledgeHub({ refresh, onChange }: Props) {
  const sources = useApi(`sources:${refresh}`, api.listSources);
  // Source and view shown in the side panel; null = closed.
  const [browsing, setBrowsing] = useState<{ source: Source; view: DrawerView } | null>(null);
  const closeDrawer = useCallback(() => setBrowsing(null), []);
  const openDrawer = useCallback((source: Source, view: DrawerView) => setBrowsing({ source, view }), []);

  const list = sources.data ?? [];
  const books = readyBooks(list);
  // Book being worked on (null = all books); forgotten when that book disappears (deleted, re-indexing).
  const [selectedBook, setSelectedBook] = useState<string | null>(null);
  const bookId = selectedBook && books.some((b) => b.id === selectedBook) ? selectedBook : null;
  const processing = list.some(isProcessing);
  const { reload } = sources;
  useEffect(() => {
    if (!processing) return;
    const timer = setInterval(reload, 1000);
    return () => {
      clearInterval(timer);
      onChange(); // processing ended (or view closed): refresh counts everywhere
    };
  }, [processing, reload, onChange]);

  return (
    <>
      <UploadPanel sources={list} sourcesLoading={sources.loading} onChange={onChange} />
      <BookShelf books={books} refresh={refresh} selected={bookId} onSelect={setSelectedBook} onBrowse={openDrawer} />
      <SourcesCard sources={list} error={sources.error} onBrowse={openDrawer} onChange={onChange} />
      <BookPicker books={books} selected={bookId} onSelect={setSelectedBook} />
      <div className="bc-split">
        <AskBook bookId={bookId} onChange={onChange} />
        <GroundedGenerator refresh={refresh} bookId={bookId} onChange={onChange} />
      </div>
      {browsing?.view === "chunks" && <SourceChunksDrawer source={browsing.source} onClose={closeDrawer} />}
      {browsing?.view === "summary" && <SummaryDrawer source={browsing.source} onClose={closeDrawer} onChange={onChange} />}
    </>
  );
}
