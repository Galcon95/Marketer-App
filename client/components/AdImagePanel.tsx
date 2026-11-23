"use client";

/**
 * Ad pictures of an ad copy (inside its AssetCard): a form to make one with the image model (the book's cover in a
 * scene that fits the book, the ad's headline drawn in or no text, in a feed, story or wide format) and the pictures
 * made so far, each with download, delete and "Post to my Page" (a photo post with an editable caption, once). The
 * pictures need the access token, so they are loaded through lib/api.ts and shown from blob: URLs. When the server has
 * pictures switched off (IMAGE_PROVIDER=off, GET /health), no new ones can be made; without any, the panel is hidden.
 */

import { useState, type FormEvent } from "react";
import { Download, ExternalLink, ImagePlus, Send, Trash2, X } from "lucide-react";
import {
  adHeadlines, adImagePath, api, bookTitle, cleanText, errorMessage, fileBlobUrl, IMAGE_FORMATS, MAX_IMAGE_HEADLINE,
  type AdImage, type Asset, type FacebookStatus, type ImageFormat,
} from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { formatUsd } from "./UsagePanel";
import { Badge, Button, ErrorNote, Segmented } from "./ui";

/** blob: URLs of the pictures loaded so far, by id: a picture never changes, so it is downloaded once per tab. */
const pictures = new Map<string, Promise<string>>();

function loadPicture(imageId: string) {
  let url = pictures.get(imageId);
  if (!url) {
    url = fileBlobUrl(adImagePath(imageId));
    url.catch(() => pictures.delete(imageId));
    pictures.set(imageId, url);
  }
  return url;
}

/** CSS aspect-ratio of each format, so a picture keeps its space while it loads. */
const RATIO: Record<ImageFormat, string> = { square: "1 / 1", portrait: "4 / 5", story: "9 / 16", landscape: "16 / 9" };

/**
 * The ad pictures of one asset and the form to make another.
 * @param asset The ad copy.
 */
export default function AdImagePanel({ asset }: { asset: Asset }) {
  const [version, setVersion] = useState(0);
  const images = useApi(`ad-images:${asset.id}:${version}`, () => api.listAdImages(asset.id));
  const [open, setOpen] = useState(false);
  const [posting, setPosting] = useState<AdImage | null>(null);
  const health = useApi("health:pictures", api.health);
  const facebook = useApi("facebook-status", api.facebookStatus);
  const list = images.data ?? [];
  // Unknown (still loading, or an older server without the entry) counts as on: the server refuses if it is not.
  const switchedOff = health.data?.services.find((s) => s.name === "images")?.detail.startsWith("off") ?? false;
  const reload = () => setVersion((v) => v + 1);

  if (switchedOff && list.length === 0) return null;
  return (
    <div className="bc-stack" style={{ gap: 10 }}>
      <div className="bc-row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <div className="bc-label">Ad pictures</div>
        {list.length > 0 && <Badge mono>{list.length}</Badge>}
        <span style={{ flex: 1 }} />
        {switchedOff
          ? <span className="bc-hint" style={{ margin: 0 }}>Pictures are switched off on the server</span>
          : !open && <Button size="sm" variant="secondary" icon={ImagePlus} onClick={() => setOpen(true)}>Create image</Button>}
      </div>
      {open && !switchedOff && <AdImageForm asset={asset} onClose={() => setOpen(false)} onCreated={reload} />}
      {posting && (
        <PostPictureForm key={posting.id} image={posting} caption={cleanText(asset.text)} facebook={facebook.data}
          onClose={() => setPosting(null)} onPosted={() => { setPosting(null); reload(); }} />
      )}
      {images.error && <ErrorNote>{images.error}</ErrorNote>}
      {list.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(min(200px, 100%), 1fr))", gap: 12 }}>
          {[...list].reverse().map((image) => (
            <AdImageTile key={image.id} image={image} onDeleted={reload}
              onPost={facebook.data?.connected && !image.published_url ? () => setPosting(image) : undefined} />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Post one picture on the author's Facebook Page: the caption (the ad copy's text, without citation markers, to
 * edit) and, after a confirmation, POST /ad-images/{id}/publish/facebook. A picture is posted once.
 */
function PostPictureForm({ image, caption, facebook, onClose, onPosted }: {
  image: AdImage; caption: string; facebook?: FacebookStatus; onClose: () => void; onPosted: () => void;
}) {
  const [text, setText] = useState(caption);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const page = facebook?.page?.name ?? "your Facebook Page";

  /** Post after a confirmation that shows the exact caption. */
  async function post(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!window.confirm(`Post this picture on ${page} now? Everyone can see it.\n\n${text.trim()}`)) return;
    setBusy(true);
    setError(null);
    try {
      await api.publishAdImage(image.id, text.trim());
      onPosted();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={post} className="bc-stack"
      style={{ gap: 10, padding: 12, border: "1px solid var(--border)", borderRadius: "var(--radius-md)", background: "var(--surface-sunken)" }}>
      <label className="bc-label" htmlFor={`caption-${image.id}`}>
        Caption for the picture{image.headline ? ` “${image.headline}”` : ""} on {page}
      </label>
      <textarea id={`caption-${image.id}`} className="bc-input" rows={6} value={text} maxLength={63206}
        onChange={(e) => setText(e.target.value)} placeholder="The text shown above the picture" />
      <span className="bc-hint" style={{ margin: 0 }}>
        Taken from the ad copy: keep one variant and delete the rest (and labels like &ldquo;Headline:&rdquo;).
      </span>
      {error && <ErrorNote>{error}</ErrorNote>}
      <div className="bc-row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <Button type="submit" size="sm" icon={Send} loading={busy} disabled={!text.trim()}>Post to my Page</Button>
        <Button size="sm" variant="ghost" icon={X} onClick={onClose} disabled={busy}>Cancel</Button>
      </div>
    </form>
  );
}

/**
 * The form: headline (one click on a headline of the ad copy, or typed; or no text at all), the author's wish for
 * the scene, the format, and the book when the asset is about several.
 */
function AdImageForm({ asset, onClose, onCreated }: { asset: Asset; onClose: () => void; onCreated: () => void }) {
  const suggestions = adHeadlines(asset.text);
  const [headline, setHeadline] = useState(suggestions[0]?.slice(0, MAX_IMAGE_HEADLINE) ?? "");
  const [noText, setNoText] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const needsBook = asset.source_ids.length !== 1;
  const sources = useApi(needsBook ? "sources" : null, () => api.listSources());
  const books = (sources.data ?? []).filter((s) => s.status === "ready"
    && (asset.source_ids.length === 0 || asset.source_ids.includes(s.id)));

  /** Ask the server for a picture (about 15 s); on success show it in the gallery and close the form. */
  async function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await api.createAdImage(asset.id, {
        headline: noText ? "" : headline.trim(),
        scene: String(form.get("scene") ?? "").trim(),
        format: String(form.get("format")) as ImageFormat,
        ...(needsBook ? { source_id: String(form.get("book") ?? "") } : {}),
      });
      onCreated();
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={create} className="bc-stack"
      style={{ gap: 12, padding: 12, border: "1px solid var(--border)", borderRadius: "var(--radius-md)", background: "var(--surface-sunken)" }}>
      <div className="bc-field">
        <label className="bc-label" htmlFor={`headline-${asset.id}`}>Headline in the picture</label>
        <input id={`headline-${asset.id}`} className="bc-input" value={noText ? "" : headline} disabled={noText}
          maxLength={MAX_IMAGE_HEADLINE} onChange={(e) => setHeadline(e.target.value)}
          placeholder={noText ? "No text in the picture" : "e.g. What if your city thought with you?"} />
        {suggestions.length > 0 && !noText && (
          <div className="bc-row" style={{ gap: 6, flexWrap: "wrap" }}>
            <span className="bc-hint" style={{ margin: 0 }}>From the ad:</span>
            {suggestions.map((s) => (
              <button key={s} type="button" className="plain-button" onClick={() => setHeadline(s.slice(0, MAX_IMAGE_HEADLINE))}
                title="Use this headline">
                <Badge tone={s.slice(0, MAX_IMAGE_HEADLINE) === headline ? "accent" : "neutral"}>{s}</Badge>
              </button>
            ))}
          </div>
        )}
        <label className="bc-row" style={{ gap: 6, alignItems: "center", fontSize: 13 }}>
          <input type="checkbox" checked={noText} onChange={(e) => setNoText(e.target.checked)} />
          No text in the picture (add your own later)
        </label>
      </div>

      <div className="bc-field">
        <label className="bc-label" htmlFor={`scene-${asset.id}`}>Scene (optional)</label>
        <input id={`scene-${asset.id}`} name="scene" className="bc-input" maxLength={300}
          placeholder="e.g. on a café table, morning light, a city skyline behind" />
      </div>

      <Segmented name="format" label="Format" defaultValue="square"
        options={IMAGE_FORMATS.map((f) => ({ value: f.value, label: `${f.label} ${f.ratio}` }))} />
      <span className="bc-hint" style={{ marginTop: -6 }}>
        {IMAGE_FORMATS.map((f) => `${f.label}: ${f.hint}`).join(" · ")}
      </span>

      {needsBook && (
        <div className="bc-field">
          <label className="bc-label" htmlFor={`book-${asset.id}`}>Book whose cover it shows</label>
          <select id={`book-${asset.id}`} name="book" className="bc-select" required defaultValue="">
            <option value="" disabled>{sources.loading ? "Loading the books…" : "Choose a book"}</option>
            {books.map((b) => <option key={b.id} value={b.id}>{bookTitle(b.filename)}</option>)}
          </select>
        </div>
      )}

      {error && <ErrorNote>{error}</ErrorNote>}
      <div className="bc-row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <Button type="submit" size="sm" icon={ImagePlus} loading={busy}
          disabled={!noText && !headline.trim()}>{busy ? "Creating…" : "Create image"}</Button>
        <Button size="sm" variant="ghost" icon={X} onClick={onClose} disabled={busy}>Cancel</Button>
        <span className="bc-hint" style={{ margin: 0 }}>
          Takes about 15 seconds and costs about $0.07, counted in your usage. The book&rsquo;s cover goes into the picture.
        </span>
      </div>
    </form>
  );
}

/**
 * One picture: shown in its format (click: full size in a new tab), with headline, cost, download, delete and (when
 * `onPost` is given: a Page is connected and it is not posted yet) "Post to my Page"; once posted, a link to the post.
 */
function AdImageTile({ image, onDeleted, onPost }: { image: AdImage; onDeleted: () => void; onPost?: () => void }) {
  const picture = useApi(`ad-image:${image.id}`, () => loadPicture(image.id));
  const [error, setError] = useState<string | null>(null);
  const format = IMAGE_FORMATS.find((f) => f.value === image.format);

  /** Delete the picture after confirmation. */
  async function remove() {
    if (!window.confirm("Delete this picture?")) return;
    try {
      await api.deleteAdImage(image.id);
      onDeleted();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <figure className="bc-stack" style={{ gap: 6, margin: 0, minWidth: 0 }}>
      {picture.data ? (
        <a href={picture.data} target="_blank" rel="noopener noreferrer" title="Open full size">
          {/* eslint-disable-next-line @next/next/no-img-element -- dynamic image from the API, not a static asset */}
          <img src={picture.data} alt={image.headline ? `Ad picture: ${image.headline}` : "Ad picture without text"}
            style={{ width: "100%", aspectRatio: RATIO[image.format], objectFit: "cover", display: "block",
              borderRadius: "var(--radius-md)", border: "1px solid var(--border)" }} />
        </a>
      ) : (
        <div style={{ width: "100%", aspectRatio: RATIO[image.format], borderRadius: "var(--radius-md)",
          border: "1px solid var(--border)", background: "var(--surface-sunken)", display: "grid", placeItems: "center" }}
          className="bc-hint">
          {picture.error ? "Could not load the picture" : "Loading…"}
        </div>
      )}
      <figcaption className="bc-stack" style={{ gap: 4 }}>
        <span style={{ fontSize: 13, overflowWrap: "anywhere" }}>{image.headline || <em className="bc-hint">no text</em>}</span>
        <div className="bc-row" style={{ gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          <Badge mono>{format ? `${format.label} ${format.ratio}` : image.format}</Badge>
          {image.cost != null && <span className="bc-hint" style={{ margin: 0 }}>{formatUsd(image.cost)}</span>}
          <span style={{ flex: 1 }} />
          {picture.data && (
            <a href={picture.data} download={`ad-${image.format}-${image.id}.png`} className="bc-btn bc-btn-ghost bc-btn-sm"
              title="Download the PNG" aria-label="Download the picture">
              <Download size={14} className="bc-ico" aria-hidden />
            </a>
          )}
          {onPost && (
            <Button size="sm" variant="ghost" icon={Send} onClick={onPost} title="Post to my Facebook Page"
              aria-label="Post the picture to my Facebook Page" />
          )}
          <Button size="sm" variant="ghost" icon={Trash2} onClick={remove} title="Delete" aria-label="Delete the picture" />
        </div>
        {image.published_url && (
          <a href={image.published_url} target="_blank" rel="noopener noreferrer" className="bc-hint" style={{ margin: 0 }}>
            Posted on your Page <ExternalLink size={12} aria-hidden />
          </a>
        )}
        {error && <ErrorNote>{error}</ErrorNote>}
      </figcaption>
    </figure>
  );
}
