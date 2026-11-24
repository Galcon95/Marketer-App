"use client";

/**
 * Scan Reddit or Substack (Discussion Relevance Agent, "Scan" modes): the author enters a topic, the server searches
 * Reddit threads or Substack posts and Notes and ranks them by how well the chosen book fits them
 * (POST /discussions/scan; nothing is saved). Each one can be handed to the agent: its text goes into the paste form
 * for the author to check first.
 *
 * The search (Tavily) gives titles and snippets, and for some threads the post with its top comments ("Full text";
 * on Substack the article, without its comments). It gives no votes, comment counts or dates. For a thread with only a
 * snippet the author opens it and copies the discussion into the form. A thread whose text looks like a prompt
 * injection gets a warning badge (InjectionBadge.tsx); it can still be analysed, as quoted data.
 */

import { useState, type SubmitEvent } from "react";
import { Bot, ChevronDown, ExternalLink, FileText, Radar, SearchX, TextQuote } from "lucide-react";
import {
  api, errorMessage, type Fit, type ScanResult, type ScanSite, type ScanTime, type ScannedThread,
} from "@/lib/api";
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
const RESULT_COUNTS = [10, 20]; // threads per search (per subreddit or publication); Tavily returns at most 20
const MAX_COMMUNITIES = 5; // as the server's ScanRequest

/** What differs between the sites: names, the communities field, texts. */
export const SITES: Record<ScanSite, {
  name: string; items: string; community: string; communities: string; placeholder: string; empty: string;
}> = {
  reddit: {
    name: "Reddit", items: "threads", community: "subreddit", communities: "Subreddits",
    placeholder: "e.g. Futurology, singularity, philosophy (empty = all of Reddit)",
    empty: "Reddit had no threads on this topic in that time. Try other words, a longer time range or other subreddits.",
  },
  substack: {
    name: "Substack", items: "posts", community: "publication", communities: "Publications",
    placeholder: "e.g. importai, innovationex (empty = all of Substack)",
    empty: "Substack had no posts on this topic in that time. Try other words, a longer time range or other publications.",
  },
};

/** The thread as text for the agent: the title, then the post and comments, or the snippet when that is all. */
export function threadAsDiscussion(t: ScannedThread): string {
  return `Title: ${t.title}\n\n${t.full_text || t.snippet}`.trim();
}

/** Subreddit or publication names from the input: separated by commas or spaces ("r/" or a link allowed). */
function parseNames(text: string): string[] {
  return text.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean);
}

/** Where a found thread is, as shown: "r/Futurology", "importai" (a publication) or "@author" (a Note). */
function communityLabel(t: ScannedThread): string {
  const community = t.community ?? t.subreddit;
  return (t.site ?? "reddit") === "reddit" ? `r/${community}` : community || "Substack";
}

/**
 * The scan form (settings column of the Discussions tab); the threads found go to `onResult` and are shown by
 * ScanResults in the wide column.
 * @param site Reddit or Substack.
 * @param bookId The book the threads are ranked for (undefined = no book chosen).
 * @param bookTitle Its readable title.
 * @param onResult Called with each new scan result.
 */
export default function RedditScan({ site = "reddit", bookId, bookTitle, onResult }: {
  site?: ScanSite; bookId?: string; bookTitle?: string; onResult: (result: ScanResult) => void;
}) {
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [communities, setCommunities] = useState("");
  const s = SITES[site];
  const names = parseNames(communities);
  const tooMany = names.length > MAX_COMMUNITIES;

  /** Form submit: search the site and rank what was found for the book. */
  async function scan(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!bookId) return;
    const form = new FormData(e.currentTarget);
    setScanning(true);
    setError(null);
    try {
      onResult(await api.scanDiscussions({
        source_id: bookId, topic: String(form.get("topic") ?? "").trim(), site,
        ...(site === "reddit" ? { subreddits: names } : { publications: names }),
        time_range: String(form.get("time") || "month") as ScanTime, max_results: Number(form.get("count") || 10),
      }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setScanning(false);
    }
  }

  return (
    <form className="bc-stack" onSubmit={scan}>
        <span className="bc-hint">
          Enter a topic. The app searches recent {site === "reddit" ? "Reddit threads" : "Substack posts and Notes"} and
          ranks them by how well {bookTitle ? <strong>{bookTitle}</strong> : "the book"} could add to them. Pick one to
          let the agent analyse it. Nothing is posted: you post replies yourself.
          {site === "substack" && " Comments under a post are not found, so the agent answers the post itself; " +
            "publications on their own web address (not …substack.com) are not found either."}
        </span>
        <div className="bc-field">
          <label className="bc-label" htmlFor={`f-scan-topic-${site}`}>Topic</label>
          <input id={`f-scan-topic-${site}`} name="topic" className="bc-input" required maxLength={300}
            placeholder="e.g. AI future, AI societies, civilizations" />
        </div>
        <div className="bc-field">
            <label className="bc-label" htmlFor={`f-scan-subs-${site}`}>{s.communities} (optional)</label>
            <input id={`f-scan-subs-${site}`} name="communities" className="bc-input" value={communities}
              onChange={(e) => setCommunities(e.target.value)} placeholder={s.placeholder} />
            <span className="bc-hint" style={tooMany ? { color: "var(--danger-text)" } : undefined}>
              {tooMany ? `At most ${MAX_COMMUNITIES} ${s.communities.toLowerCase()}.`
                : `One search per ${s.community}, at most ${MAX_COMMUNITIES}.`}
            </span>
        </div>
        <div className="bc-row" style={{ gap: 12, alignItems: "flex-start", flexWrap: "nowrap" }}>
          <div className="bc-field" style={{ flex: 1 }}>
            <label className="bc-label" htmlFor={`f-scan-time-${site}`}>Time</label>
            <div className="bc-select-wrap">
              <select id={`f-scan-time-${site}`} name="time" className="bc-select" defaultValue="month">
                {TIME_RANGES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
              <ChevronDown size={16} className="bc-ico" aria-hidden />
            </div>
          </div>
          <div className="bc-field" style={{ flex: 1 }}>
            <label className="bc-label" htmlFor={`f-scan-count-${site}`}>{site === "reddit" ? "Threads" : "Posts"} / search</label>
            <div className="bc-select-wrap">
              <select id={`f-scan-count-${site}`} name="count" className="bc-select" defaultValue={10}>
                {RESULT_COUNTS.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
              <ChevronDown size={16} className="bc-ico" aria-hidden />
            </div>
          </div>
        </div>
        <div className="bc-studio-actions">
          <Button type="submit" icon={Radar} loading={scanning} disabled={!bookId || tooMany}>
            {scanning ? `Scanning ${s.name}…` : `Scan ${s.name}`}
          </Button>
        </div>
        {!bookId && <span className="bc-hint">Choose a book under &ldquo;Working on&rdquo; first: the scan ranks {s.items} for one book.</span>}
        {scanning && <span className="bc-hint">This takes 5-20 seconds: one search per {s.community}, then the {s.items} are ranked.</span>}
        {error && <ErrorNote>{error}</ErrorNote>}
    </form>
  );
}

/**
 * The threads of a scan, best fit first; low-fit ones only on request.
 * @param result The scan result.
 * @param onAnalyse Called with a thread to analyse: its text and link go to the paste form.
 */
export function ScanResults({ result, onAnalyse }: { result: ScanResult; onAnalyse: (thread: ScannedThread) => void }) {
  const [showLow, setShowLow] = useState(false);
  const s = SITES[result.site ?? "reddit"];
  const threads = result.threads;
  const shown = threads.filter((t) => showLow || t.fit !== "low");
  const hidden = threads.length - shown.length;
  return (
        <div className="bc-stack" style={{ gap: 10 }}>
          <span className="bc-label" style={{ margin: 0 }}>
            {threads.length
              ? `${shown.length} of ${threads.length} ${s.items}${result.found > threads.length ? ` (best ${threads.length} of ${result.found} ranked)` : ""}`
              : `No ${s.items} found`}
          </span>
          {shown.length ? shown.map((t) => (
            <ThreadRow key={t.url} thread={t} onAnalyse={() => onAnalyse(t)} />
          )) : (
            <Placeholder icon={SearchX}>
              {threads.length
                ? `Nothing fits the book well. Show the low-fit ${s.items}, or try another topic or a longer time range.`
                : s.empty}
            </Placeholder>
          )}
          {hidden > 0 && (
            <Button variant="ghost" size="sm" onClick={() => setShowLow(true)}>
              Show {hidden} low-fit {hidden > 1 ? s.items : s.items.slice(0, -1)}
            </Button>
          )}
        </div>
  );
}

/** One found thread: fit, where it is, whether its text is there, the title, an excerpt, why the book fits, actions. */
function ThreadRow({ thread: t, onAnalyse }: { thread: ScannedThread; onAnalyse: () => void }) {
  const fit = FIT[t.fit];
  const excerpt = t.full_text || t.snippet;
  return (
    <div className="bc-cite-src" style={{ borderLeft: 0, borderRadius: "var(--radius-md)", padding: 12 }}>
      <div className="bc-row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <Badge tone={fit.tone} dot>{fit.label}</Badge>
        <span className="bc-hint"><strong>{communityLabel(t)}</strong></span>
        {t.full_text
          ? <Badge icon={FileText}>Full text</Badge>
          : <span title="The search had only a short excerpt. Open it and copy the text."><Badge icon={TextQuote}>Snippet only</Badge></span>}
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
          <ExternalLink size={14} className="bc-ico" aria-hidden />Open on {SITES[t.site ?? "reddit"].name}
        </a>
      </div>
    </div>
  );
}
