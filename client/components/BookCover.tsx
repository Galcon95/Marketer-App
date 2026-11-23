"use client";

/**
 * Book covers extracted from the PDFs (BookCover, with a placeholder while loading or if there is none) and
 * PageLink, which opens the original PDF at a cited page. Both files need the user's access token, so they are
 * downloaded through lib/api.ts and shown from blob: URLs instead of plain <img src> / <a href> links to the API.
 */

import { useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { BookOpen, ImageUp } from "lucide-react";
import { api, coverPath, errorMessage, fileBlobUrl, filePath } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { Button } from "./ui";

/** blob: URLs of the covers loaded so far, by source id: a cover shown in several places is downloaded once. */
const covers = new Map<string, Promise<string>>();
/** How often each cover was replaced in this tab: part of the load key, so every BookCover shows the new one. */
const coverVersions = new Map<string, number>();
const coverListeners = new Set<() => void>();

/** Forget a book's cover after it was replaced, so every place that shows it loads the new one. */
function coverChanged(sourceId: string) {
  const old = covers.get(sourceId);
  covers.delete(sourceId);
  old?.then((url) => setTimeout(() => URL.revokeObjectURL(url), 5000), () => {});
  coverVersions.set(sourceId, (coverVersions.get(sourceId) ?? 0) + 1);
  coverListeners.forEach((listener) => listener());
}

/** How often this book's cover was replaced in this tab (0 = never), re-rendering when it changes. */
function useCoverVersion(sourceId: string) {
  return useSyncExternalStore(
    (listener) => {
      coverListeners.add(listener);
      return () => coverListeners.delete(listener);
    },
    () => coverVersions.get(sourceId) ?? 0,
    () => 0,
  );
}

/** The cover's blob: URL, downloaded on first use; a failed download is forgotten, so it is tried again later. */
function loadCover(sourceId: string) {
  let url = covers.get(sourceId);
  if (!url) {
    url = fileBlobUrl(coverPath(sourceId));
    url.catch(() => covers.delete(sourceId));
    covers.set(sourceId, url);
  }
  return url;
}

/** How long a PDF's blob: URL stays valid after opening it; the new tab's viewer has loaded the file by then. */
const PDF_URL_LIFETIME_MS = 60_000;

/**
 * Open a source's PDF in a new tab, at a page if given (#page=N is understood by the PDF viewers of Chrome, Edge,
 * Firefox and Safari). The tab is opened at once (inside the click, so popup blockers allow it) and gets the PDF
 * when it has been downloaded with the access token.
 * @param sourceId The source.
 * @param page Optional 1-based page to open at.
 */
async function openPdf(sourceId: string, page?: number | null) {
  const tab = window.open("", "_blank");
  if (!tab) return; // blocked by the browser
  tab.document.title = "Opening PDF…";
  try {
    const url = await fileBlobUrl(filePath(sourceId));
    tab.location.href = page ? `${url}#page=${page}` : url;
    setTimeout(() => URL.revokeObjectURL(url), PDF_URL_LIFETIME_MS);
  } catch (e) {
    tab.document.body.textContent = `Could not open the PDF: ${errorMessage(e)}`;
  }
}


/**
 * Cover image of a book, in book proportions (2:3), served by the API (GET /sources/{id}/cover).
 * Falls back to a book icon on a neutral tile while loading, if the PDF has no usable cover or the API is down.
 * With `link`, clicking it opens the book's PDF in a new browser tab.
 * @param sourceId The book (source) whose cover to show.
 * @param title Book title, for the image's alt text.
 * @param width Width in px; the height is 1.5 × width.
 * @param link Make the cover a link that opens the PDF in a new tab.
 */
export default function BookCover({ sourceId, title, width, link }: { sourceId: string; title: string; width: number; link?: boolean }) {
  const version = useCoverVersion(sourceId);
  const cover = useApi(`cover:${sourceId}:${version}`, () => loadCover(sourceId));
  const height = Math.round(width * 1.5);
  const frame = {
    width, height, flexShrink: 0, borderRadius: width < 60 ? "var(--radius-sm)" : "var(--radius-md)",
    border: "1px solid var(--border)", boxShadow: width < 60 ? undefined : "var(--shadow-pop)",
  } as const;

  let image: ReactNode;
  if (!cover.data) {
    image = (
      <div style={{ ...frame, display: "grid", placeItems: "center", background: "var(--surface-sunken)", color: "var(--ink-muted)" }}
        role="img" aria-label={cover.error ? `No cover for ${title}` : `Loading the cover of ${title}`}>
        <BookOpen size={Math.min(28, Math.round(width / 2.5))} aria-hidden />
      </div>
    );
  } else {
    image = (
      // eslint-disable-next-line @next/next/no-img-element -- dynamic image from the API, not a static asset for next/image
      <img src={cover.data} alt={`Cover of ${title}`} width={width} height={height}
        style={{ ...frame, objectFit: "cover", background: "var(--surface-sunken)" }} />
    );
  }
  if (!link) return image;
  return (
    <button type="button" onClick={() => openPdf(sourceId)} title={`Open "${title}" (PDF) in a new tab`}
      className="plain-button" style={{ flexShrink: 0, borderRadius: frame.borderRadius }}>
      {image}
    </button>
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
    <button type="button" onClick={() => openPdf(sourceId, page)} title={`Open the PDF at page ${page}`} className="plain-button">
      {children}
    </button>
  );
}

/** Largest cover file the server accepts (api/sources.py MAX_COVER_BYTES). */
const MAX_COVER_BYTES = 10 * 1024 * 1024;

/**
 * "Change cover": upload the author's own cover picture (PNG or JPEG, e.g. the newest front cover) for a book. The
 * server keeps only its pixels and uses it in the library and in every ad picture made from then on.
 * @param sourceId The book.
 * @param title Book title, for the button's label.
 */
export function ChangeCoverButton({ sourceId, title }: { sourceId: string; title: string }) {
  const input = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  /** Upload the chosen file, then show the new cover everywhere (or tell why it was refused). */
  async function upload(file: File | undefined) {
    if (!file) return;
    if (file.size > MAX_COVER_BYTES) {
      window.alert("The picture is larger than 10 MB. Please choose a smaller PNG or JPEG.");
      return;
    }
    setUploading(true);
    try {
      await api.uploadCover(sourceId, file);
      coverChanged(sourceId);
    } catch (e) {
      window.alert(`The cover could not be changed: ${errorMessage(e)}`);
    } finally {
      setUploading(false);
      if (input.current) input.current.value = ""; // the same file can be chosen again
    }
  }

  return (
    <>
      <input ref={input} type="file" accept="image/png,image/jpeg" hidden
        onChange={(e) => upload(e.target.files?.[0])} aria-label={`New cover for ${title}`} />
      <Button size="sm" variant="ghost" icon={ImageUp} loading={uploading} onClick={() => input.current?.click()}
        title="Upload your own cover (PNG or JPEG, up to 10 MB). It is used here and in every new ad picture.">
        Change cover
      </Button>
    </>
  );
}
