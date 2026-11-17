"use client";

/**
 * The comments under the videos of the author's own YouTube channel (Discussion Relevance Agent, "own channel" mode):
 * the latest comment threads, grouped by video, each comment with who wrote it and whether the channel has answered
 * it. A comment can be handed to the agent: the video, the comment and the replies under it go into the paste form,
 * and the agent answers it as the author (GET /youtube/comments; nothing is posted from here).
 *
 * YouTube threads are two levels deep: a top comment and the replies under it (parent_id = the top comment).
 */

import { useState } from "react";
import { Bot, CheckCheck, ExternalLink, MessagesSquare, RefreshCw } from "lucide-react";
import { api, type YouTubeComment, type YouTubeThread } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import InjectionBadge from "./InjectionBadge";
import { Badge, Button, ErrorNote, Placeholder } from "./ui";

/** The top comment of a comment's thread (itself when it is one). */
function topOf(thread: YouTubeThread, comment: YouTubeComment): YouTubeComment {
  return (comment.parent_id && thread.comments.find((c) => c.id === comment.parent_id)) || comment;
}

/** The replies under a top comment, oldest first. */
function repliesOf(thread: YouTubeThread, top: YouTubeComment): YouTubeComment[] {
  return thread.comments.filter((c) => c.parent_id === top.id).reverse();
}

/**
 * The comment as text for the agent: the video, the comment, then the replies under it (yours as "Me"). For a
 * follow-up inside a thread: the top comment and the replies before the follow-up, then the follow-up to answer.
 */
export function videoCommentAsDiscussion(thread: YouTubeThread, comment: YouTubeComment): string {
  const name = (c: YouTubeComment) => (c.from_channel ? "Me (the author)" : c.author ?? "A viewer");
  const video = `My video on my YouTube channel: ${thread.video.title || "(title not available)"}`;
  const list = (cs: YouTubeComment[]) => cs.map((r) => `- ${name(r)}: ${r.message}`).join("\n");
  const top = topOf(thread, comment);
  if (top.id !== comment.id) {
    const before = repliesOf(thread, top).filter((r) => r.id !== comment.id && r.created_time <= comment.created_time);
    return [
      video,
      `Comment by ${name(top)}:\n${top.message}`,
      ...(before.length ? [`Replies to it:\n${list(before)}`] : []),
      `The follow-up to answer now, by ${name(comment)}:\n${comment.message}`,
    ].join("\n\n");
  }
  const replies = repliesOf(thread, comment);
  return [
    video,
    `Comment by ${name(comment)}:\n${comment.message}`,
    ...(replies.length ? [`Replies to it:\n${list(replies)}`] : []),
  ].join("\n\n");
}

const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

/**
 * The channel's recent comments, grouped by video.
 * @param channelName The channel's name, for the texts.
 * @param onAnalyse Called with a video and one of its comments to analyse.
 */
export default function YouTubeComments({ channelName, onAnalyse }: {
  channelName: string; onAnalyse: (thread: YouTubeThread, comment: YouTubeComment) => void;
}) {
  const [nonce, setNonce] = useState(0);
  const threads = useApi(`youtube-comments:${nonce}`, () => api.youtubeComments(50));
  const [showAnswered, setShowAnswered] = useState(false);

  const all = threads.data ?? [];
  // Viewers' unanswered comments, top comments and follow-ups in a thread; answered top comments only on request.
  const open = (t: YouTubeThread) => t.comments.filter((c) => !c.from_channel && (!c.answered || (showAnswered && !c.parent_id)));
  const answeredCount = all.reduce((n, t) => n + t.comments.filter((c) => !c.from_channel && !c.parent_id && c.answered).length, 0);
  const shown = all.filter((t) => open(t).length > 0);

  return (
    <div className="bc-stack">
      <div className="bc-row" style={{ gap: 8, alignItems: "baseline" }}>
        <span className="bc-hint" style={{ flex: 1, margin: 0 }}>
          The latest comments under the videos of <strong>{channelName}</strong>. Pick one: the agent answers it as you,
          from the book. You check the reply and post it as your channel with one click, or copy it.
        </span>
        <Button size="sm" variant="success" icon={RefreshCw} loading={threads.loading} onClick={() => setNonce((n) => n + 1)}>
          Refresh
        </Button>
      </div>
      {threads.error && <ErrorNote>{threads.error}</ErrorNote>}
      {shown.map((t) => (
        <div key={t.video.id} className="bc-cite-src" style={{ borderLeft: 0, borderRadius: "var(--radius-md)", padding: 12 }}>
          <div className="bc-row" style={{ gap: 8, alignItems: "center" }}>
            {t.video.thumbnail && (
              // eslint-disable-next-line @next/next/no-img-element -- a small remote thumbnail, no optimisation needed
              <img src={t.video.thumbnail} alt="" width={80} height={45} style={{ borderRadius: 4, objectFit: "cover", flex: "none" }} />
            )}
            <span className="bc-label" style={{ margin: 0, flex: 1 }}>{t.video.title || "A video of your channel"}</span>
            <a className="bc-btn bc-btn-ghost bc-btn-sm" href={t.video.url} target="_blank" rel="noopener noreferrer">
              <ExternalLink size={14} className="bc-ico" aria-hidden />Open on YouTube
            </a>
          </div>
          <div className="bc-stack" style={{ gap: 8, marginTop: 8 }}>
            {open(t).map((c) => {
              const top = topOf(t, c);
              const followUp = top.id !== c.id;
              const replies = followUp ? 0 : repliesOf(t, c).length;
              return (
                <div key={c.id} style={{ borderTop: "1px solid var(--border)", paddingTop: 8 }}>
                  <div className="bc-row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <strong style={{ fontSize: 13 }}>{c.author ?? "A viewer"}</strong>
                    <span className="bc-hint" style={{ margin: 0 }}>{when(c.created_time)}</span>
                    {c.answered && <Badge tone="success" icon={CheckCheck}>answered</Badge>}
                    <InjectionBadge risk={c.injection_risk} findings={c.injection_findings} />
                    {replies > 0 && <Badge>{replies} repl{replies > 1 ? "ies" : "y"}</Badge>}
                    {followUp && <Badge tone="accent">follow-up</Badge>}
                    {c.permalink_url && (
                      <a className="bc-hint" style={{ margin: 0 }} href={c.permalink_url} target="_blank" rel="noopener noreferrer">
                        open <ExternalLink size={12} aria-hidden />
                      </a>
                    )}
                  </div>
                  {followUp && (
                    <span className="bc-hint" style={{ display: "block", margin: "4px 0 0" }}>
                      In the thread of {top.from_channel ? "your channel" : top.author ?? "a viewer"}: &ldquo;
                      {top.message.length > 90 ? `${top.message.slice(0, 90)}…` : top.message}&rdquo;
                    </span>
                  )}
                  <p style={{ margin: "4px 0 8px", whiteSpace: "pre-wrap" }}>{c.message || "(no text)"}</p>
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
          {answeredCount ? "Every recent comment on your videos is answered." : "No comments on your videos yet."}
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
