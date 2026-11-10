"use client";

/**
 * Scan Reddit (Discussion Relevance Agent, "Scan" mode): the author enters a topic, the server searches Reddit and
 * ranks the threads found by how well the chosen book fits them (POST /discussions/scan; nothing is saved). Each
 * thread can be handed to the agent: its text goes into the paste form for the author to check first.
 *
 * The search (Tavily) gives titles and snippets, and for some threads the post with its top comments ("Full text").
 * It gives no votes, comment counts or dates. For a thread with only a snippet the author opens it on Reddit and
 * copies the discussion into the form. A thread whose text looks like a prompt injection gets a warning badge
 * (InjectionBadge.tsx); it can still be analysed, as quoted data.
 */

import { useState, type SubmitEvent } from "react";
import { Bot, ChevronDown, ExternalLink, FileText, Radar, SearchX, TextQuote } from "lucide-react";
import { api, errorMessage, type Fit, type ScanResult, type ScanTime, type ScannedThread } from "@/lib/api";
import InjectionBadge from "./InjectionBadge";
import { Badge, Button, ErrorNote, Placeholder } from "./ui";

const FIT: Record<Fit, { label: string; tone: "success" | "warning" | "neutral" }> = {
  high: { label: "High fit", tone: "success" },
  medium: { label: "Medium fit", tone: "warning" },
  low: { label: "Low fit", tone: "neutral" },
};

const TIME_RANGES: { value: ScanTime; label: string }[] = [
  { value: "week", label: "Past week" },
  { value: "month", label: "Past month" },
  { value: "year", label: "Past year" },
];
const RESULT_COUNTS = [10, 20]; // threads per search (per subreddit); Tavily returns at most 20
const MAX_SUBREDDITS = 5; // as the server's ScanRequest

/** The thread as text for the agent: the title, then the post and comments, or the snippet when that is all. */
export function threadAsDiscussion(t: ScannedThread): string {
  return `Title: ${t.title}\n\n${t.full_text || t.snippet}`.trim();
}

/** Subreddit names from the input: separated by commas or spaces, "r/" allowed. */
function parseSubreddits(text: string): string[] {
  return text.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean);
}

/**
 * The scan form and its results (kept while the author switches to the paste form and back).
 * @param bookId The book the threads are ranked for (undefined = no book chosen).
 * @param bookTitle Its readable title.
 * @param onAnalyse Called with a thread to analyse: its text and link go to the paste form.
 */
export default function RedditScan({ bookId, bookTitle, onAnalyse }: {
  bookId?: string; bookTitle?: string; onAnalyse: (thread: ScannedThread) => void;
}) {
  const [scanning, setScanning] = useState(false);
  const [result, setResult] = useState<ScanResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [subreddits, setSubreddits] = useState("");
  const [showLow, setShowLow] = useState(false);

  const subs = parseSubreddits(subreddits);
  const tooManySubs = subs.length > MAX_SUBREDDITS;

  /** Form submit: search Reddit and rank the threads for the book. */
  async function scan(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!bookId) return;
    const form = new FormData(e.currentTarget);
    setScanning(true);
    setError(null);
    setShowLow(false);
    try {
      setResult(await api.scanDiscussions({
        source_id: bookId, topic: String(form.get("topic") ?? "").trim(), subreddits: subs,
        time_range: String(form.get("time") || "month") as ScanTime, max_results: Number(form.get("count") || 10),
      }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setScanning(false);
    }
  }

  const threads = result?.threads ?? [];
  const shown = threads.filter((t) => showLow || t.fit !== "low");
  const hidden = threads.length - shown.length;

  return (
    <div className="bc-stack">
      <form className="bc-stack" onSubmit={scan}>
        <span className="bc-hint">
          Enter a topic. The app searches recent Reddit threads and ranks them by how well{" "}
          {bookTitle ? <strong>{bookTitle}</strong> : "the book"} could add to them. Pick one to let the agent
          analyse it. Nothing is posted: you post replies yourself.
        </span>
        <div className="bc-field">
          <label className="bc-label" htmlFor="f-scan-topic">Topic</label>
          <input id="f-scan-topic" name="topic" className="bc-input" required maxLength={300}
            placeholder="e.g. AI future, AI societies, civilizations" />
        </div>
        <div className="bc-row" style={{ gap: 12, alignItems: "flex-start" }}>
          <div className="bc-field" style={{ flex: "3 1 280px" }}>
            <label className="bc-label" htmlFor="f-scan-subs">Subreddits (optional)</label>
            <input id="f-scan-subs" name="subreddits" className="bc-input" value={subreddits}
              onChange={(e) => setSubreddits(e.target.value)}
              placeholder="e.g. Futurology, singularity, philosophy (empty = all of Reddit)" />
            <span className="bc-hint" style={tooManySubs ? { color: "var(--danger-text)" } : undefined}>
              {tooManySubs ? `At most ${MAX_SUBREDDITS} subreddits.` : "One search per subreddit, at most 5."}
            </span>
          </div>
          <div className="bc-field" style={{ flex: "1 1 140px" }}>
            <label className="bc-label" htmlFor="f-scan-time">Time</label>
            <div className="bc-select-wrap">
              <select id="f-scan-time" name="time" className="bc-select" defaultValue="month">
                {TIME_RANGES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
              <ChevronDown size={16} className="bc-ico" aria-hidden />
            </div>
          </div>
          <div className="bc-field" style={{ flex: "1 1 120px" }}>
            <label className="bc-label" htmlFor="f-scan-count">Threads per search</label>
            <div className="bc-select-wrap">
              <select id="f-scan-count" name="count" className="bc-select" defaultValue={10}>
                {RESULT_COUNTS.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
              <ChevronDown size={16} className="bc-ico" aria-hidden />
            </div>
          </div>
        </div>
        <Button type="submit" icon={Radar} loading={scanning} disabled={!bookId || tooManySubs}>
          {scanning ? "Scanning Reddit…" : "Scan Reddit"}
        </Button>
        {!bookId && <span className="bc-hint">Choose a book under &ldquo;Working on&rdquo; first: the scan ranks threads for one book.</span>}
        {scanning && <span className="bc-hint">This takes 5-20 seconds: one search per subreddit, then the threads are ranked.</span>}
        {error && <ErrorNote>{error}</ErrorNote>}
      </form>

      {result && (
        <div className="bc-stack" style={{ gap: 10 }}>
          <span className="bc-label" style={{ margin: 0 }}>
            {threads.length
              ? `${shown.length} of ${threads.length} threads${result.found > threads.length ? ` (best ${threads.length} of ${result.found} ranked)` : ""}`
              : "No threads found"}
          </span>
          {shown.length ? shown.map((t) => (
            <ThreadRow key={t.url} thread={t} onAnalyse={() => onAnalyse(t)} />
          )) : (
            <Placeholder icon={SearchX}>
              {threads.length
                ? "No thread fits the book well. Show the low-fit ones, or try another topic or a longer time range."
                : "Reddit had no threads on this topic in that time. Try other words, a longer time range or other subreddits."}
            </Placeholder>
          )}
          {hidden > 0 && (
            <Button variant="ghost" size="sm" onClick={() => setShowLow(true)}>
              Show {hidden} low-fit thread{hidden > 1 ? "s" : ""}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

/** One found thread: fit, subreddit, whether its text is there, the title, an excerpt, why the book fits, actions. */
function ThreadRow({ thread: t, onAnalyse }: { thread: ScannedThread; onAnalyse: () => void }) {
  const fit = FIT[t.fit];
  const excerpt = t.full_text || t.snippet;
  return (
    <div className="bc-cite-src" style={{ borderLeft: 0, borderRadius: "var(--radius-md)", padding: 12 }}>
      <div className="bc-row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <Badge tone={fit.tone} dot>{fit.label}</Badge>
        <span className="bc-hint"><strong>r/{t.subreddit}</strong></span>
        {t.full_text
          ? <Badge icon={FileText}>Full text</Badge>
          : <span title="The search had only a short excerpt. Open the thread and copy the discussion."><Badge icon={TextQuote}>Snippet only</Badge></span>}
        <InjectionBadge risk={t.injection_risk} findings={t.injection_findings} />
      </div>
      <div style={{ fontWeight: 600, margin: "8px 0 4px" }}>{t.title}</div>
      {excerpt && (
        <p className="bc-hint" style={{
          margin: 0, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden",
        }}>{excerpt}</p>
      )}
      <p style={{ margin: "8px 0 0", fontSize: 13 }}><strong>Why:</strong> {t.why}</p>
      <div className="bc-row" style={{ gap: 8, marginTop: 10, flexWrap: "wrap" }}>
        <Button size="sm" icon={Bot} variant={t.fit === "low" ? "secondary" : "primary"} onClick={onAnalyse}>
          Analyse with agent
        </Button>
        <a className="bc-btn bc-btn-ghost bc-btn-sm" href={t.url} target="_blank" rel="noopener noreferrer">
          <ExternalLink size={14} className="bc-ico" aria-hidden />Open on Reddit
        </a>
      </div>
    </div>
  );
}
