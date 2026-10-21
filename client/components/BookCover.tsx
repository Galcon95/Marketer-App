"use client";

import { useState, type ReactNode } from "react";
import { BookOpen } from "lucide-react";
import { coverUrl, fileUrl } from "@/lib/api";

/**
 * Cover image of a book, in book proportions (2:3), served by the API (GET /sources/{id}/cover).
 * Falls back to a book icon on a neutral tile if the PDF has no usable cover or the API is down.
 * With `link`, clicking it opens the book's PDF in a new browser tab.
 * @param sourceId The book (source) whose cover to show.
 * @param title Book title, for the image's alt text.
 * @param width Width in px; the height is 1.5 × width.
 * @param link Make the cover a link that opens the PDF in a new tab.
 */
export default function BookCover({ sourceId, title, width, link }: { sourceId: string; title: string; width: number; link?: boolean }) {
  const [failed, setFailed] = useState(false);
  const height = Math.round(width * 1.5);
  const frame = {
    width, height, flexShrink: 0, borderRadius: width < 60 ? "var(--radius-sm)" : "var(--radius-md)",
    border: "1px solid var(--border)", boxShadow: width < 60 ? undefined : "var(--shadow-pop)",
  } as const;

  let cover: ReactNode;
  if (failed) {
    cover = (
      <div style={{ ...frame, display: "grid", placeItems: "center", background: "var(--surface-sunken)", color: "var(--ink-muted)" }}
        role="img" aria-label={`No cover for ${title}`}>
        <BookOpen size={Math.min(28, Math.round(width / 2.5))} aria-hidden />
      </div>
    );
  } else {
    cover = (
      // eslint-disable-next-line @next/next/no-img-element -- dynamic image from the API, not a static asset for next/image
      <img src={coverUrl(sourceId)} alt={`Cover of ${title}`} width={width} height={height} loading="lazy"
        onError={() => setFailed(true)} style={{ ...frame, objectFit: "cover", background: "var(--surface-sunken)" }} />
    );
  }
  if (!link) return cover;
  return (
    <a href={fileUrl(sourceId)} target="_blank" rel="noopener noreferrer" title={`Open "${title}" (PDF) in a new tab`}
      style={{ display: "inline-flex", flexShrink: 0, borderRadius: frame.borderRadius }}>
      {cover}
    </a>
  );
}

/**
 * A location badge (e.g. "INTRODUCTION. · p.9") that opens the source's PDF at that page in a new tab.
 * Renders its children unchanged when there is no page (e.g. media timestamps).
 * @param sourceId The source the location belongs to.
 * @param page 1-based page, or null.
 * @param children The badge to make clickable.
 */
export function PageLink({ sourceId, page, children }: { sourceId: string; page: number | null; children: ReactNode }) {
  if (!page) return <>{children}</>;
  return (
    <a href={fileUrl(sourceId, page)} target="_blank" rel="noopener noreferrer" title={`Open the PDF at page ${page}`}
      style={{ textDecoration: "none", color: "inherit", cursor: "pointer" }}>
      {children}
    </a>
  );
}
