"use client";

/**
 * Phase 1, Knowledge Hub (RAG over the client's books):
 *   UploadPanel / SourcesCard   upload PDFs, follow ingestion progress, process, re-index, delete
 *   BookShelf / BookPicker      the library with covers; choose one book or all books to work on
 *   SourceChunksDrawer          browse a book's chunks; SummaryDrawer: create and read the book summary
 *   AskBook                     "Ask your book": chat with history, citations and tool calls
 * Writing content from the books happens in the Content Studio (Phase 2).
 */

import { useCallback, useEffect, useRef, useState, type MouseEvent, type ReactNode, type SubmitEvent } from "react";
import { AlertTriangle, BookOpen, Check, Database, FileText, Film, Library, MessageSquare, Play, Plus, RotateCcw, Sparkles, Target, Trash2, Upload, Wrench } from "lucide-react";
import {
  api, bookTitle, errorMessage, locationLabel, MAX_UPLOAD_BYTES, PROCESSING_STATUSES, UPLOAD_EXTENSIONS,
  type BookSummary, type ChatTurn, type Chunk, type ChunkPage, type Source, type ToolCallRecord,
} from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { CitationList } from "../AssetCard";
import BookCover, { PageLink } from "../BookCover";
import BookPicker, { readyBooks } from "../BookPicker";
import { Badge, Button, Card, Drawer, ErrorNote, Field, Placeholder, ProgressBar, Score, SectionHeading } from "../ui";

/** Props every phase view gets from AppShell (see PhaseProps there). */
type Props = {
  refresh: number; onChange: () => void; bookId: string | null; onSelectBook: (id: string | null) => void;
};

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

/* ---------- Deleting a book ---------- */
/** "1 chat" / "2 chats". */
function plural(n: number, word: string) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/**
 * Ask for confirmation, naming what will also go (from GET /sources/{id}/deletion), then delete the book.
 * Used by the book cards and the sources table, so the question is always the same.
 * @param source The book to delete.
 * @returns True if it was deleted, false if the user cancelled. Rejects on API errors.
 */
async function confirmAndDeleteBook(source: Source): Promise<boolean> {
  const preview = await api.previewDeletion(source.id);
  const also = [
    "its chunks and summary",
    preview.assets ? `${plural(preview.assets, "generated text")} made only from it` : "",
    preview.conversations ? `${plural(preview.conversations, "chat")} that only used it` : "",
  ].filter(Boolean);
  const message = [
    `Delete "${preview.name}"?`,
    `This also deletes ${also.join(", ")}. Texts and chats that also draw on other books are kept.`,
    "This cannot be undone.",
  ].join("\n\n");
  if (!window.confirm(message)) return false;
  await api.deleteSource(source.id);
  return true;
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
function BookShelf({ books, refresh, selected, onSelect, onBrowse, onDelete }: {
  books: Source[]; refresh: number; selected: string | null;
  onSelect: (id: string | null) => void; onBrowse: (source: Source, view: DrawerView) => void;
  onDelete: (source: Source) => void;
}) {
  if (books.length === 0) return null;
  return (
    <div>
      <SectionHeading icon={Library} title="Your books" count={books.length} />
      <div className="bc-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(420px, 100%), 1fr))" }}>
        {books.map((book) => (
          <BookCard key={book.id} source={book} refresh={refresh} selected={selected === book.id}
            onSelect={() => onSelect(selected === book.id ? null : book.id)} onBrowse={onBrowse}
            onDelete={() => onDelete(book)} />
        ))}
      </div>
    </div>
  );
}

/**
 * One book on the shelf: cover (click: opens the PDF), title, chunk/chapter/size badges, the first sentences of its summary
 * and up to four key themes, with buttons to open the summary (or create it) and the chunks.
 * The book being worked on is highlighted with an accent border; clicking another card makes it the one worked on.
 * @param source The book.
 * @param refresh Changing it reloads the summary.
 * @param selected True if this is the book being worked on.
 * @param onSelect Toggles this book as the one being worked on.
 * @param onBrowse Opens the summary or chunks panel.
 * @param onDelete Deletes the book (after a confirmation).
 */
function BookCard({ source, refresh, selected, onSelect, onBrowse, onDelete }: {
  source: Source; refresh: number; selected: boolean; onSelect: () => void; onBrowse: (source: Source, view: DrawerView) => void;
  onDelete: () => void;
}) {
  const summary = useApi(`book-summary:${source.id}:${refresh}`, () => api.getSummary(source.id));
  const s = summary.data;
  const title = bookTitle(source.filename);

  /** A click anywhere on the card (outside its buttons and links) makes this the book being worked on. It never
   * deselects, so an accidental click cannot drop the choice; the "Working on this book" button does that. */
  function pickFromCard(e: MouseEvent<HTMLDivElement>) {
    if (!selected && !(e.target as HTMLElement).closest("button, a")) onSelect();
  }

  return (
    <Card className={selected ? "book-selected" : "book-pickable"}>
      <div style={{ display: "flex", gap: 20, alignItems: "flex-start" }} onClick={pickFromCard}
        title={selected ? undefined : "Click to work on this book"}>
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
            <Button size="sm" variant="ghost" icon={Trash2} onClick={onDelete} title="Delete this book"
              aria-label={`Delete ${title}`} />
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
   * Delete a book after a confirmation that names what also goes (confirmAndDeleteBook), then refresh the app.
   * @param source The book to delete.
   */
  async function remove(source: Source) {
    setActionError(null);
    try {
      if (await confirmAndDeleteBook(source)) onChange();
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
                      <Button variant="ghost" size="sm" icon={Trash2} aria-label={`Delete ${s.filename}`} onClick={() => remove(s)} />
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
 * "Ask your book" as a chat, NotebookLM-style: each question is answered by the LLM from the most
 * relevant passages of the project's books (POST /ask), and follow-ups can refer to earlier turns
 * ("and in chapter 3?"); the server rewrites them into a standalone question before searching, shown
 * as "Searched for". Each answer shows its [n] citations and, collapsed, all retrieved passages with
 * their scores. Chats are saved on the server: "Past chats" reopens or deletes them, "New chat" starts over.
 * @param bookId Only use this book; null = all books.
 * @param onChange Called after each answer, so the usage totals in the top bar update.
 */
function AskBook({ bookId, onChange }: { bookId: string | null; onChange: () => void }) {
  const [conversationId, setConversationId] = useState<string | null>(null); // open chat; null = a new chat
  const [turns, setTurns] = useState<ChatTurn[]>([]); // questions and answers of the open chat, oldest first
  const [pending, setPending] = useState<string | null>(null); // question being answered right now
  const [error, setError] = useState<string | null>(null);
  const [listVersion, setListVersion] = useState(0); // bump to reload the past chats
  const past = useApi(`conversations:${listVersion}`, api.listConversations);
  const endRef = useRef<HTMLDivElement>(null);

  // Keep the newest turn (or the pending question) in view.
  useEffect(() => {
    if (turns.length || pending) endRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [turns.length, pending]);

  /** Form submit: send the question as the next turn of the open chat (or start one); clears the input on success. */
  async function submit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const question = String(new FormData(form).get("q") ?? "").trim();
    if (!question || pending) return;
    setPending(question);
    setError(null);
    try {
      const turn = await api.ask(question, 6, bookId ? [bookId] : undefined, conversationId ?? undefined);
      setTurns((t) => [...t, { ...turn, created_at: new Date().toISOString() }]);
      setConversationId(turn.conversation_id);
      form.reset();
      setListVersion((v) => v + 1);
      onChange();
    } catch (err) {
      setError(errorMessage(err)); // the question stays in the input, so it can be fixed and sent again
    } finally {
      setPending(null);
    }
  }

  /** Open a past chat with all its turns. */
  async function open(id: string) {
    setError(null);
    try {
      const conversation = await api.getConversation(id);
      setConversationId(conversation.id);
      setTurns(conversation.turns);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  /** Start a new, empty chat (the open one stays saved). */
  function newChat() {
    setConversationId(null);
    setTurns([]);
    setError(null);
  }

  /** Delete a past chat; closes it if it is the open one. */
  async function remove(id: string) {
    try {
      await api.deleteConversation(id);
      if (id === conversationId) newChat();
      setListVersion((v) => v + 1);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const tokens = turns.reduce((n, t) => n + t.tokens, 0);
  const chats = past.data ?? [];
  return (
    <Card title="Ask your book" icon={MessageSquare}
      meta={tokens ? <Badge mono>{tokens.toLocaleString()} tokens</Badge> : undefined}
      actions={turns.length ? <Button size="sm" variant="ghost" icon={Plus} onClick={newChat} disabled={!!pending}>New chat</Button> : undefined}>
      <div className="bc-stack">
        {turns.length === 0 && !pending && (
          <span className="bc-hint">
            Ask anything about your uploaded books, then keep asking follow-up questions. Answers are written
            only from the most relevant passages, with numbered citations; if the books don&apos;t cover it, it says so.
            The assistant can also use tools: list your books, check a post for a platform (&quot;Does this fit on X? …&quot;)
            or draft a post (&quot;Write a LinkedIn post about …&quot;).
          </span>
        )}
        {turns.map((turn, i) => <ChatTurnView key={`${turn.created_at}-${i}`} turn={turn} first={i === 0} />)}
        {pending && (
          <div className="bc-stack" style={{ gap: 8, ...(turns.length ? TURN_DIVIDER : {}) }}>
            <QuestionLine question={pending} />
            <Placeholder icon={MessageSquare}>
              {turns.length ? "Reading the conversation and the relevant passages, using tools if needed…"
                : "Reading the relevant passages, using tools if needed…"}
            </Placeholder>
          </div>
        )}
        <div ref={endRef} />
        {error && <ErrorNote>{error}</ErrorNote>}
        <form className="bc-row" style={{ flexWrap: "nowrap" }} onSubmit={submit}>
          <div style={{ flex: 1 }}>
            <Field name="q" as="search"
              placeholder={turns.length ? "Ask a follow-up, e.g. And who collects that money?" : "e.g. How will Garden City be financed?"} />
          </div>
          <Button type="submit" variant="secondary" icon={Sparkles} loading={!!pending}>Ask</Button>
        </form>
        {chats.length > 0 && (
          <details>
            <summary className="bc-hint" style={{ cursor: "pointer" }}>Past chats ({chats.length})</summary>
            <div className="bc-stack" style={{ gap: 4, marginTop: 8 }}>
              {chats.map((c) => (
                <div key={c.id} className="bc-row" style={{ flexWrap: "nowrap", gap: 8 }}>
                  <Button size="sm" variant="ghost" icon={MessageSquare} onClick={() => open(c.id)} disabled={!!pending}
                    title="Open this chat">
                    {c.title}
                  </Button>
                  <span className="bc-hint" style={{ flex: 1, whiteSpace: "nowrap" }}>
                    {c.turn_count} {c.turn_count === 1 ? "question" : "questions"} · {new Date(c.updated_at).toLocaleString()}
                  </span>
                  {c.id === conversationId && <Badge tone="accent">open</Badge>}
                  <Button size="sm" variant="ghost" icon={Trash2} aria-label={`Delete chat "${c.title}"`}
                    onClick={() => remove(c.id)} disabled={!!pending} />
                </div>
              ))}
            </div>
          </details>
        )}
        {past.error && <ErrorNote>{past.error}</ErrorNote>}
      </div>
    </Card>
  );
}

/** Line between two turns of a chat. */
const TURN_DIVIDER = { borderTop: "1px solid var(--border)", paddingTop: 16 };

/** The user's question in a chat, marked "You". */
function QuestionLine({ question }: { question: string }) {
  return (
    <div className="bc-row" style={{ flexWrap: "nowrap", gap: 8, alignItems: "baseline" }}>
      <Badge tone="accent">You</Badge>
      <strong>{question}</strong>
    </div>
  );
}

/** Short labels of the chat tools, shown on their cards. */
const TOOL_LABELS: Record<string, string> = {
  list_books: "Looked up the library",
  check_platform_fit: "Checked the post for the platform",
  draft_social_post: "Drafted a post (saved to the asset library)",
};

/**
 * A tool the chat model called for an answer: what it did, with which arguments, whether it worked and how
 * long it took; the full result (JSON) is collapsed below.
 * @param call The tool call.
 */
function ToolCallCard({ call }: { call: ToolCallRecord }) {
  const args = JSON.stringify(call.arguments);
  return (
    <details className="bc-cite-src" style={{ borderLeft: 0, borderRadius: "var(--radius-md)" }}>
      <summary className="bc-row" style={{ gap: 8, cursor: "pointer", flexWrap: "wrap" }}>
        <Badge tone={call.ok ? "accent" : "danger"} icon={Wrench} mono>{call.name}</Badge>
        <span className="bc-hint">{call.ok ? TOOL_LABELS[call.name] ?? "Called a tool" : "Tool call failed"}</span>
        <Badge mono>{call.duration_ms} ms</Badge>
      </summary>
      <div className="bc-stack" style={{ gap: 6, marginTop: 8 }}>
        <span className="bc-hint bc-mono" style={{ wordBreak: "break-word" }}>
          arguments: {args.length > 300 ? args.slice(0, 297) + "…" : args}
        </span>
        <pre className="bc-mono" style={{ margin: 0, padding: 10, maxHeight: 300, overflow: "auto", fontSize: 12,
          whiteSpace: "pre-wrap", wordBreak: "break-word", background: "var(--surface-sunken)",
          border: "1px solid var(--border)", borderRadius: "var(--radius-md)" }}>
          {typeof call.result === "string" ? call.result : JSON.stringify(call.result, null, 2)}
        </pre>
      </div>
    </details>
  );
}

/**
 * One turn of an "Ask your book" chat: the question, what was searched (when a follow-up was rewritten), the
 * book/chapter/page filter taken from the question, the tools the model called, the answer, its cited passages and, collapsed, all retrieved passages.
 * @param turn The question and answer.
 * @param first True for the first turn (no divider above it).
 */
function ChatTurnView({ turn, first }: { turn: ChatTurn; first: boolean }) {
  const rewritten = turn.search_query.trim().toLowerCase() !== turn.question.trim().toLowerCase();
  return (
    <div className="bc-stack" style={{ gap: 8, ...(first ? {} : TURN_DIVIDER) }}>
      <QuestionLine question={turn.question} />
      {rewritten && (
        <span className="bc-hint" title="Follow-up questions are rewritten into a standalone question before searching the books">
          Searched for: “{turn.search_query}”
        </span>
      )}
      {turn.filters && (
        <span className="bc-hint" title="Structured retrieval: the book, chapter or pages named in the question restrict the search">
          Filtered to: {turn.filters}
        </span>
      )}
      {(turn.tool_calls ?? []).map((call, i) => <ToolCallCard key={i} call={call} />)}
      <p style={{ whiteSpace: "pre-wrap", margin: 0 }}>{turn.answer}</p>
      <CitationList citations={turn.citations} />
      <details>
        <summary className="bc-hint" style={{ cursor: "pointer" }}>
          All retrieved passages ({turn.passages.length}) · {turn.tokens.toLocaleString()} tokens
        </summary>
        <div className="bc-stack" style={{ marginTop: 8 }}>
          {turn.passages.map((h) => <ChunkCard key={h.chunk.id} chunk={h.chunk} score={h.score} />)}
        </div>
      </details>
    </div>
  );
}

/* ---------- Phase 1 ---------- */
/**
 * Phase 1: the knowledge hub for retrieval-augmented generation. Combines upload, the book shelf, the sources
 * table and "Ask your book" (questions answered from the books), and opens the chunk and summary drawers.
 * While any source is being processed, the sources list is reloaded every second so the upload
 * panel and the table show live progress; when processing ends, the whole app is refreshed once
 * (sidebar counts, project stats).
 * @param refresh Changing it reloads sources and assets.
 * @param onChange Called after any change (upload, delete, generate) to refresh the app.
 * @param bookId The book being worked on, shared across the app (null = all books).
 * @param onSelectBook Changes the book being worked on.
 */
export default function KnowledgeHub({ refresh, onChange, bookId: selectedBook, onSelectBook }: Props) {
  const sources = useApi(`sources:${refresh}`, api.listSources);
  // Source and view shown in the side panel; null = closed.
  const [browsing, setBrowsing] = useState<{ source: Source; view: DrawerView } | null>(null);
  const closeDrawer = useCallback(() => setBrowsing(null), []);
  const openDrawer = useCallback((source: Source, view: DrawerView) => setBrowsing({ source, view }), []);

  const list = sources.data ?? [];
  const books = readyBooks(list);
  // Book being worked on (null = all books); ignored while that book is not ready (deleted, re-indexing).
  const bookId = selectedBook && books.some((b) => b.id === selectedBook) ? selectedBook : null;
  const processing = list.some(isProcessing);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  /** Delete a book from its card (after the confirmation); closes its side panel if that is open. */
  async function deleteBook(source: Source) {
    setDeleteError(null);
    try {
      if (!(await confirmAndDeleteBook(source))) return;
      if (browsing?.source.id === source.id) closeDrawer();
      onChange();
    } catch (e) {
      setDeleteError(errorMessage(e));
    }
  }
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
      <BookShelf books={books} refresh={refresh} selected={bookId} onSelect={onSelectBook} onBrowse={openDrawer}
        onDelete={deleteBook} />
      {deleteError && <ErrorNote>{deleteError}</ErrorNote>}
      <SourcesCard sources={list} error={sources.error} onBrowse={openDrawer} onChange={onChange} />
      <BookPicker books={books} selected={bookId} onSelect={onSelectBook} uses="Ask your book uses" />
      <AskBook bookId={bookId} onChange={onChange} />
      {browsing?.view === "chunks" && <SourceChunksDrawer source={browsing.source} onClose={closeDrawer} />}
      {browsing?.view === "summary" && <SummaryDrawer source={browsing.source} onClose={closeDrawer} onChange={onChange} />}
    </>
  );
}
