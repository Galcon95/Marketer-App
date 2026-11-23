"use client";

/**
 * Ad pictures of an ad copy (inside its AssetCard): a form to make one with the image model (the book's cover in a
 * scene that fits the book, the ad's headline drawn in or no text, in a feed, story or wide format) and the pictures
 * made so far, each with download and delete. The pictures need the access token, so they are loaded through
 * lib/api.ts and shown from blob: URLs.
 */

import { useState, type FormEvent } from "react";
import { Download, ImagePlus, Trash2, X } from "lucide-react";
import {
  adHeadlines, adImagePath, api, bookTitle, errorMessage, fileBlobUrl, IMAGE_FORMATS, MAX_IMAGE_HEADLINE,
  type AdImage, type Asset, type ImageFormat,
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
  const list = images.data ?? [];

  return (
    <div className="bc-stack" style={{ gap: 10 }}>
      <div className="bc-row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <div className="bc-label">Ad pictures</div>
        {list.length > 0 && <Badge mono>{list.length}</Badge>}
        <span style={{ flex: 1 }} />
        {!open && <Button size="sm" variant="secondary" icon={ImagePlus} onClick={() => setOpen(true)}>Create image</Button>}
      </div>
      {open && <AdImageForm asset={asset} onClose={() => setOpen(false)} onCreated={() => setVersion((v) => v + 1)} />}
      {images.error && <ErrorNote>{images.error}</ErrorNote>}
      {list.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(min(200px, 100%), 1fr))", gap: 12 }}>
          {[...list].reverse().map((image) => (
            <AdImageTile key={image.id} image={image} onDeleted={() => setVersion((v) => v + 1)} />
          ))}
        </div>
      )}
    </div>
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

/** One picture: shown in its format (click: full size in a new tab), with headline, cost, download and delete. */
function AdImageTile({ image, onDeleted }: { image: AdImage; onDeleted: () => void }) {
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
          <Button size="sm" variant="ghost" icon={Trash2} onClick={remove} title="Delete" aria-label="Delete the picture" />
        </div>
        {error && <ErrorNote>{error}</ErrorNote>}
      </figcaption>
    </figure>
  );
}
