"use client";

/**
 * The comments on the author's own Facebook Page (Discussion Relevance Agent, "Facebook Page" mode; the user's own Page):
 * the latest posts that have comments, each comment with who wrote it and whether the Page has answered it. A comment
 * can be handed to the agent: the post, the comment and the replies under it go into the paste form, and the agent
 * answers it as the author (GET /facebook/comments; nothing is posted from here).
 */

import { useState } from "react";
import { Bot, CheckCheck, ExternalLink, MessagesSquare, RefreshCw } from "lucide-react";
import { api, type FacebookComment, type FacebookThread } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import InjectionBadge from "./InjectionBadge";
import { Badge, Button, ErrorNote, Placeholder } from "./ui";

/** The top-level comment a comment belongs to (itself when it is one), following parent_id up the thread. */
function rootOf(thread: FacebookThread, comment: FacebookComment): FacebookComment {
  let c = comment;
  for (let i = 0; i < 10 && c.parent_id; i++) {
    const parent = thread.comments.find((x) => x.id === c.parent_id);
    if (!parent) break;
    c = parent;
  }
  return c;
}

/** All replies in the thread of a top-level comment (at any depth), oldest first. */
function threadReplies(thread: FacebookThread, root: FacebookComment): FacebookComment[] {
  return thread.comments.filter((c) => c.id !== root.id && rootOf(thread, c).id === root.id).reverse();
}

/**
 * The comment as text for the agent: the Page post, the comment, then the replies under it (yours as "Me"). For a
 * follow-up inside a thread: the thread's first comment and the replies before the follow-up, then the follow-up as
 * the comment to answer.
 */
export function commentAsDiscussion(thread: FacebookThread, comment: FacebookComment): string {
  const name = (c: FacebookComment) => (c.from_page ? "Me (the author)" : c.author ?? "A reader");
  const post = `My post on my Facebook Page:\n${thread.post.message || "(a photo or video without text)"}`;
  const list = (cs: FacebookComment[]) => cs.map((r) => `- ${name(r)}: ${r.message}`).join("\n");
  if (comment.parent_id) {
    const root = rootOf(thread, comment);
    const before = threadReplies(thread, root)
      .filter((r) => r.id !== comment.id && r.created_time <= comment.created_time);
    return [
      post,
      `Comment by ${name(root)}:\n${root.message}`,
      ...(before.length ? [`Replies to it:\n${list(before)}`] : []),
      `The follow-up to answer now, by ${name(comment)}:\n${comment.message}`,
    ].join("\n\n");
  }
  const replies = threadReplies(thread, comment);
  return [
    post,
    `Comment by ${name(comment)}:\n${comment.message}`,
    ...(replies.length ? [`Replies to it:\n${list(replies)}`] : []),
  ].join("\n\n");
}

const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

/**
 * The Page's recent comments, grouped by post.
 * @param pageName The Page's name, for the texts.
 * @param onAnalyse Called with a post and one of its comments to analyse.
 */
export default function FacebookComments({ pageName, onAnalyse }: {
  pageName: string; onAnalyse: (thread: FacebookThread, comment: FacebookComment) => void;
}) {
  const [nonce, setNonce] = useState(0);
  const threads = useApi(`facebook-comments:${nonce}`, () => api.facebookComments(10));
  const [showAnswered, setShowAnswered] = useState(false);

  const all = threads.data ?? [];
  // Readers' unanswered comments, top-level ones and follow-ups inside a thread (e.g. a new question after the Page's
  // reply); answered top-level comments only on request (their replies come with them).
  const open = (t: FacebookThread) => t.comments.filter((c) => !c.from_page && (!c.answered || (showAnswered && !c.parent_id)));
  const answeredCount = all.reduce((n, t) => n + t.comments.filter((c) => !c.from_page && !c.parent_id && c.answered).length, 0);
  const shown = all.filter((t) => open(t).length > 0);

  return (
    <div className="bc-stack">
      <div className="bc-row" style={{ gap: 8, alignItems: "baseline" }}>
        <span className="bc-hint" style={{ flex: 1, margin: 0 }}>
          Comments on the latest posts of <strong>{pageName}</strong>. Pick one: the agent answers it as you, from the
          book. You check the reply and post it as your Page with one click, or copy it.
        </span>
        <Button size="sm" variant="success" icon={RefreshCw} loading={threads.loading} onClick={() => setNonce((n) => n + 1)}>
          Refresh
        </Button>
      </div>
      {threads.error && <ErrorNote>{threads.error}</ErrorNote>}
      {shown.map((t) => (
        <div key={t.post.id} className="bc-cite-src" style={{ borderLeft: 0, borderRadius: "var(--radius-md)", padding: 12 }}>
          <div className="bc-row" style={{ gap: 8, alignItems: "baseline" }}>
            <span className="bc-label" style={{ margin: 0, flex: 1 }}>Your post · {when(t.post.created_time)}</span>
            {t.post.permalink_url && (
              <a className="bc-btn bc-btn-ghost bc-btn-sm" href={t.post.permalink_url} target="_blank" rel="noopener noreferrer">
                <ExternalLink size={14} className="bc-ico" aria-hidden />Open on Facebook
              </a>
            )}
          </div>
          <p className="bc-hint" style={{
            margin: "4px 0 8px", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden",
          }}>{t.post.message || "(a photo or video without text)"}</p>
          <div className="bc-stack" style={{ gap: 8 }}>
            {open(t).map((c) => {
              const replies = c.parent_id ? 0 : threadReplies(t, c).length;
              const root = c.parent_id ? rootOf(t, c) : null; // set for a follow-up inside a thread
              return (
                <div key={c.id} style={{ borderTop: "1px solid var(--border)", paddingTop: 8 }}>
                  <div className="bc-row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <strong style={{ fontSize: 13 }}>{c.author ?? "A reader"}</strong>
                    <span className="bc-hint" style={{ margin: 0 }}>{when(c.created_time)}</span>
                    {c.answered && <Badge tone="success" icon={CheckCheck}>answered</Badge>}
                    <InjectionBadge risk={c.injection_risk} findings={c.injection_findings} />
                    {replies > 0 && <Badge>{replies} repl{replies > 1 ? "ies" : "y"}</Badge>}
                    {root && <Badge tone="accent">follow-up</Badge>}
                  </div>
                  {root && (
                    <span className="bc-hint" style={{ display: "block", margin: "4px 0 0" }}>
                      In the thread of {root.from_page ? "your Page" : root.author ?? "a reader"}: &ldquo;
                      {root.message.length > 90 ? `${root.message.slice(0, 90)}…` : root.message}&rdquo;
                    </span>
                  )}
                  <p style={{ margin: "4px 0 8px", whiteSpace: "pre-wrap" }}>{c.message || "(no text: a sticker or picture)"}</p>
                  <Button size="sm" icon={Bot} variant={c.answered ? "secondary" : "primary"} onClick={() => onAnalyse(t, c)}
                    disabled={!c.message.trim()}>Analyse with agent</Button>
                </div>
              );
            })}
          </div>
        </div>
      ))}
      {!threads.loading && !threads.error && !shown.length && (
        <Placeholder icon={MessagesSquare}>
          {answeredCount ? "Every comment on your latest posts is answered." : "No comments on your latest posts yet."}
        </Placeholder>
      )}
      {answeredCount > 0 && (
        <Button size="sm" variant="ghost" onClick={() => setShowAnswered(!showAnswered)}>
          {showAnswered ? "Hide answered comments" : `Show ${answeredCount} answered comment${answeredCount > 1 ? "s" : ""}`}
        </Button>
      )}
    </div>
  );
}
