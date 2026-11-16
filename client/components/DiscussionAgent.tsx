"use client";

/**
 * The Discussion Relevance Agent (Phase 3, Community): paste a discussion from Reddit, LinkedIn,
 * YouTube or a forum, and the agent searches the book chosen under "Working on", recommends whether to contribute
 * (contribute, more context, skip) and drafts a reply grounded in the book's passages (POST /discussions).
 * Layout as in the Content Studio: how to find a discussion and the settings on the left, the found threads or the
 * discussion text on the right, and below them the saved analyses, newest first, to edit, copy and post.
 * "Scan Reddit" (RedditScan.tsx) finds threads to analyse. For the admin (the owner of the Facebook Page) a
 * third tab lists the comments on the Page (FacebookComments.tsx): one goes into the form, and the agent answers it as
 * the author ("own Page" mode); the reply can then be posted as the Page. Above the comments, "Write a new post"
 * (FacebookNewPost.tsx) writes a post or reader question from the book and publishes it on the Page. When the Page is
 * not configured or not reachable (e.g. an expired token), the tab stays and says why instead of disappearing.
 * Other people's text is scanned for prompt injection on the server and flagged, not blocked (InjectionBadge.tsx).
 */

import { useState, type SubmitEvent } from "react";
import { Bot, ChevronDown, ClipboardPaste, MessageCircle, MessagesSquare, Radar, X } from "lucide-react";
import {
  api, bookTitle, DISCUSSION_PLATFORMS, errorMessage, humanizeLabel, platformFromUrl, TONES, type DiscussionPlatform,
  type FacebookComment, type FacebookThread, type ScanResult, type ScannedThread, type Source, type Tone,
} from "@/lib/api";
import { useApi } from "@/lib/useApi";
import DiscussionCard from "./DiscussionCard";
import FacebookComments, { commentAsDiscussion } from "./FacebookComments";
import FacebookNewPost from "./FacebookNewPost";
import RedditScan, { ScanResults, threadAsDiscussion } from "./RedditScan";
import { Button, Card, ErrorNote, Field, Placeholder, RangeField, SectionHeading } from "./ui";

const MAX_DISCUSSION = 8000; // as the server's DiscussionRequest
const FORM = "discussion-form"; // the paste form: its settings sit in the left column, its text in the right one

/**
 * Form to analyse a discussion plus the list of saved analyses.
 * The agent works on one book: the one chosen under "Working on", or the only book there is. The link fills in
 * the platform when it is a known site (it can still be changed).
 * @param refresh Changing it reloads the list.
 * @param books The processed books.
 * @param bookId The book chosen under "Working on" (null = all books).
 * @param onChange Called after an analysis was made, edited or deleted, to refresh the app.
 */
export default function DiscussionAgent({ refresh, books, bookId, onChange }: {
  refresh: number; books: Source[]; bookId: string | null; onChange: () => void;
}) {
  const discussions = useApi(`discussions:${refresh}`, api.listDiscussions);
  const [discussion, setDiscussion] = useState("");
  const [url, setUrl] = useState("");
  const [platform, setPlatform] = useState<DiscussionPlatform>("reddit");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"scan" | "facebook" | "paste">("scan");
  const [fromScan, setFromScan] = useState<ScannedThread | null>(null); // the scanned thread loaded into the form
  const [fromPage, setFromPage] = useState<FacebookComment | null>(null); // the Page comment loaded into the form
  const [scan, setScan] = useState<ScanResult | null>(null); // the last Reddit scan (kept across modes)
  // The author's Facebook Page (403 for anyone but the admin: no Facebook tab).
  const facebook = useApi("facebook-status", api.facebookStatus);
  const isPageAdmin = facebook.data !== undefined; // the status call succeeded: the admin, connected or not
  const pageConnected = facebook.data?.connected === true;

  const book = books.find((b) => b.id === bookId) ?? (books.length === 1 ? books[0] : undefined);
  const titles = new Map(books.map((b) => [b.id, bookTitle(b.filename)]));
  // Each book as a reference for "Copy source": "Title by Author" (the author from the file name or the PDF).
  const refs = new Map(books.map((b) => {
    const [title, author = b.author] = bookTitle(b.filename).split(" — ");
    return [b.id, author ? `"${title}" by ${author}` : `"${title}"`];
  }));
  const shown = (discussions.data ?? []).filter((d) => !bookId || d.source_id === bookId);
  const tooLong = discussion.length > MAX_DISCUSSION;

  /** A new link: take over its platform when the site is known. */
  function changeUrl(value: string) {
    setUrl(value);
    const guessed = platformFromUrl(value);
    if (guessed) setPlatform(guessed);
  }

  /** A thread picked in the scan: load its text and link into the paste form, to review and run the agent. */
  function analyseThread(t: ScannedThread) {
    setDiscussion(threadAsDiscussion(t));
    setUrl(t.url);
    setPlatform("reddit");
    setFromScan(t);
    setFromPage(null);
    setMode("paste");
  }

  /** A comment picked on the Facebook Page: the post, the comment and its replies go into the form. */
  function analyseComment(thread: FacebookThread, comment: FacebookComment) {
    setDiscussion(commentAsDiscussion(thread, comment));
    setUrl(comment.permalink_url ?? thread.post.permalink_url ?? "");
    setPlatform("facebook");
    setFromPage(comment);
    setFromScan(null);
    setMode("paste");
  }

  /** Form submit: run the agent on the discussion for the chosen book; the result appears at the top of the list. */
  async function submit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!book) return;
    const form = new FormData(e.currentTarget);
    const angle = String(form.get("angle") ?? "").trim();
    const humanize = Number(form.get("humanize") || 80);
    const tone = (String(form.get("tone") || "neutral")) as Tone;
    setPending(true);
    setError(null);
    try {
      await api.analyzeDiscussion({
        source_id: book.id, discussion: discussion.trim(), url: url.trim(), platform, angle, humanize, tone,
        ...(fromPage ? { facebook_comment_id: fromPage.id } : {}),
      });
      onChange();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setPending(false);
    }
  }

  // Two columns (bc-studio, like the Content Studio): how to find a discussion and the settings on the left (stay
  // in view); the found threads or the discussion text, and the analyses, on the right.
  return (
    <div className="bc-studio">
      <div className="bc-studio-side">
        <Card>
          <div className="bc-stack">
            <div className="bc-row" role="group" aria-label="How to find a discussion" style={{ gap: 6 }}>
              <Button size="sm" icon={Radar} variant={mode === "scan" ? "secondary" : "ghost"} aria-pressed={mode === "scan"}
                onClick={() => setMode("scan")}>Scan Reddit</Button>
              {isPageAdmin && (
                <Button size="sm" icon={MessageCircle} variant={mode === "facebook" ? "secondary" : "ghost"}
                  aria-pressed={mode === "facebook"} onClick={() => setMode("facebook")}>My Page</Button>
              )}
              <Button size="sm" icon={ClipboardPaste} variant={mode === "paste" ? "secondary" : "ghost"} aria-pressed={mode === "paste"}
                onClick={() => setMode("paste")}>Paste</Button>
            </div>
            {/* hidden, not unmounted: the topic and subreddits stay while the author looks at another mode */}
            <div hidden={mode !== "scan"}>
              <RedditScan bookId={book?.id} bookTitle={book ? bookTitle(book.filename) : undefined} onResult={setScan} />
            </div>
            {mode === "facebook" && (
              <span className="bc-hint">
                Write a new post for your Facebook Page from the book, or pick a reader&apos;s comment: the agent
                answers it as you, and you can post the reply as your Page.
              </span>
            )}
            {mode === "paste" && (
              <>
                <span className="bc-hint">
                  The agent searches {book ? <strong>{bookTitle(book.filename)}</strong> : "the book"}, says whether a
                  reply from the book would help the discussion, and drafts one with its sources. You post it yourself.
                </span>
                <div className="bc-field">
                  <label className="bc-label" htmlFor="f-discussion-url">Link (optional)</label>
                  <input id="f-discussion-url" name="url" form={FORM} type="url" className="bc-input" value={url}
                    onChange={(e) => changeUrl(e.target.value)} placeholder="https://www.reddit.com/r/…" />
                </div>
                <div className="bc-field">
                  <label className="bc-label" htmlFor="f-discussion-platform">Platform</label>
                  <div className="bc-select-wrap">
                    <select id="f-discussion-platform" className="bc-select" value={platform}
                      onChange={(e) => setPlatform(e.target.value as DiscussionPlatform)}>
                      {DISCUSSION_PLATFORMS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
                    </select>
                    <ChevronDown size={16} className="bc-ico" aria-hidden />
                  </div>
                </div>
                <Field name="angle" form={FORM} label="Your angle (optional)"
                  placeholder="e.g. The book's point that people stay accountable" />
                <Field name="tone" form={FORM} as="select" label="Tone" options={TONES} />
                <RangeField name="humanize" form={FORM} label="How human?" defaultValue={80} describe={humanizeLabel}
                  ends={["Polished", "Casual"]}
                  tip="Like the generator: higher = plainer, more personal wording. From 60 on, AI clichés found in the draft are rewritten automatically." />
              </>
            )}
          </div>
        </Card>
      </div>

      <div className="bc-studio-brief">
        {mode === "scan" && (scan ? <ScanResults result={scan} onAnalyse={analyseThread} /> : (
          <Placeholder icon={Radar}>Threads found on Reddit will appear here, best fit first.</Placeholder>
        ))}
        {mode === "facebook" && facebook.data && !pageConnected && (
          <div className="bc-stack" style={{ gap: 12 }}>
            <ErrorNote>
              {facebook.data.error
                ? <>Facebook Page not reachable: {facebook.data.error}. Renew FACEBOOK_PAGE_TOKEN (and
                  FACEBOOK_USER_TOKEN) in server/.env and restart the server.</>
                : <>Facebook Page not configured: set FACEBOOK_PAGE_ID and FACEBOOK_PAGE_TOKEN in server/.env and
                  restart the server.</>}
            </ErrorNote>
            <div>
              <Button size="sm" variant="ghost" disabled={facebook.loading} onClick={facebook.reload}>
                {facebook.loading ? "Checking…" : "Check again"}
              </Button>
            </div>
          </div>
        )}
        {mode === "facebook" && pageConnected && facebook.data && (
          <Card>
            <div className="bc-stack" style={{ gap: 20 }}>
              <FacebookNewPost bookId={book?.id ?? null} facebook={facebook.data} onChange={onChange} />
              <FacebookComments pageName={facebook.data.page?.name ?? "your Page"} onAnalyse={analyseComment} />
            </div>
          </Card>
        )}
        {mode === "paste" && (
          <Card>
            <form id={FORM} className="bc-stack" onSubmit={submit}>
              {fromPage && (
                <span className="bc-hint" style={{ color: "var(--accent-text)", display: "flex", gap: 8, alignItems: "baseline" }}>
                  <span style={{ flex: 1 }}>
                    A comment on your Facebook Page by <strong>{fromPage.author ?? "a reader"}</strong>. The agent answers
                    it as you, the author; after checking the reply you can post it as your Page.
                  </span>
                  <Button size="sm" variant="ghost" icon={X} onClick={() => setFromPage(null)}
                    title="Analyse the text as an ordinary discussion instead">Not a Page comment</Button>
                </span>
              )}
              {fromScan && (
                <span className="bc-hint" style={{ color: "var(--accent-text)" }}>
                  Loaded from the scan: <strong>{fromScan.title}</strong>.{" "}
                  {fromScan.full_text
                    ? "Check the text, set angle and tone, then analyse."
                    : <>The search had only a short excerpt: <a href={fromScan.url} target="_blank" rel="noopener noreferrer">open the thread</a> and paste the post and the comments that matter, then analyse.</>}
                </span>
              )}
              <div className="bc-field">
                <label className="bc-label" htmlFor="f-discussion">The discussion</label>
                <textarea id="f-discussion" name="discussion" className="bc-textarea" rows={12} required value={discussion}
                  onChange={(e) => setDiscussion(e.target.value)}
                  placeholder={"Copy a post and the replies that matter from Reddit, LinkedIn, YouTube or a forum, e.g.\n\nTitle: Could AI actually help run a city?\n…\n\nReply 1: …"} />
                <span className="bc-hint" style={tooLong ? { color: "var(--danger-text)" } : undefined}>
                  {discussion.length.toLocaleString()} / {MAX_DISCUSSION.toLocaleString()} characters
                  {tooLong && ": shorten it, e.g. keep the post and the replies that matter"}
                </span>
              </div>
              <div className="bc-studio-actions">
                {pending && <span className="bc-hint">Up to a minute: the agent searches several times.</span>}
                <Button type="submit" icon={Bot} loading={pending} disabled={!book || tooLong || !discussion.trim()}>
                  {pending ? "The agent is searching the book…" : "Analyse discussion"}
                </Button>
              </div>
              {!book && <span className="bc-hint">Choose a book under &ldquo;Working on&rdquo; first: the agent works with one book.</span>}
              {error && <ErrorNote>{error}</ErrorNote>}
            </form>
          </Card>
        )}
      </div>

      <div className="bc-studio-results">
        <SectionHeading icon={Bot} title="Discussion analyses" count={shown.length} />
        {discussions.error ? (
          <ErrorNote>{discussions.error}</ErrorNote>
        ) : shown.length ? (
          shown.map((d) => (
            <DiscussionCard key={d.id} analysis={d} book={bookId ? undefined : titles.get(d.source_id)}
              bookRef={refs.get(d.source_id)} onChange={onChange} />
          ))
        ) : (
          <Placeholder icon={MessagesSquare}>
            {discussions.loading ? "Loading…" : `Analysed discussions${bookId ? " for this book" : ""} will appear here.`}
          </Placeholder>
        )}
      </div>
    </div>
  );
}
