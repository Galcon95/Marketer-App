"use client";

/**
 * The comments on the author's own Facebook Page (Discussion Relevance Agent, "My Facebook Page" tab; admin only):
 * the latest posts that have comments, each comment with who wrote it and whether the Page has answered it. A comment
 * can be handed to the agent: the post, the comment and the replies under it go into the paste form, and the agent
 * answers it as the author (GET /facebook/comments; nothing is posted from here).
 */

import { useState } from "react";
import { Bot, CheckCheck, ExternalLink, MessagesSquare, RefreshCw } from "lucide-react";
import { api, type FacebookComment, type FacebookThread } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { Badge, Button, ErrorNote, Placeholder } from "./ui";

/** The comment as text for the agent: the Page post, the comment, then the replies under it (yours as "Me"). */
export function commentAsDiscussion(thread: FacebookThread, comment: FacebookComment): string {
  const name = (c: FacebookComment) => (c.from_page ? "Me (the author)" : c.author ?? "A reader");
  const replies = thread.comments.filter((c) => c.parent_id === comment.id).reverse(); // oldest first
  return [
    `My post on my Facebook Page:\n${thread.post.message || "(a photo or video without text)"}`,
    `Comment by ${name(comment)}:\n${comment.message}`,
    ...(replies.length ? [`Replies to it:\n${replies.map((r) => `- ${name(r)}: ${r.message}`).join("\n")}`] : []),
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
  // Readers' top-level comments (replies under a comment come with it); answered ones only on request.
  const open = (t: FacebookThread) => t.comments.filter((c) => !c.from_page && !c.parent_id && (showAnswered || !c.answered));
  const answeredCount = all.reduce((n, t) => n + t.comments.filter((c) => !c.from_page && !c.parent_id && c.answered).length, 0);
  const shown = all.filter((t) => open(t).length > 0);

  return (
    <div className="bc-stack">
      <div className="bc-row" style={{ gap: 8, alignItems: "baseline" }}>
        <span className="bc-hint" style={{ flex: 1, margin: 0 }}>
          Comments on the latest posts of <strong>{pageName}</strong>. Pick one: the agent answers it as you, from the
          book. You check the reply and post it as your Page with one click, or copy it.
        </span>
        <Button size="sm" variant="ghost" icon={RefreshCw} loading={threads.loading} onClick={() => setNonce((n) => n + 1)}>
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
              const replies = t.comments.filter((r) => r.parent_id === c.id).length;
              return (
                <div key={c.id} style={{ borderTop: "1px solid var(--border)", paddingTop: 8 }}>
                  <div className="bc-row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <strong style={{ fontSize: 13 }}>{c.author ?? "A reader"}</strong>
                    <span className="bc-hint" style={{ margin: 0 }}>{when(c.created_time)}</span>
                    {c.answered && <Badge tone="success" icon={CheckCheck}>answered</Badge>}
                    {replies > 0 && <Badge>{replies} repl{replies > 1 ? "ies" : "y"}</Badge>}
                  </div>
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
