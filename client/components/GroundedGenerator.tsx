"use client";

/**
 * The grounded asset generator (Content Studio, "Single asset"): writes a blurb, post, reply, video script,
 * newsletter, ad copy, lead magnet or persona from the books, with citations (POST /generate), and lists the
 * generated assets of the selected type below the form.
 */

import { useState, type SubmitEvent } from "react";
import { Sparkles } from "lucide-react";
import {
  api, ASSET_TYPES, assetTypeLabel, errorMessage, humanizeLabel, LENGTHS, PLANNED_ASSET_TYPES, PLATFORMS, TONES, usesPlatform,
  type AssetType, type Length, type Platform, type Tone,
} from "@/lib/api";
import { useApi } from "@/lib/useApi";
import AssetCard from "./AssetCard";
import { Button, Card, ErrorNote, Field, Placeholder, RangeField, SectionHeading } from "./ui";

/** Example brief per asset type, shown as the brief's placeholder (for replies: the optional angle). */
const BRIEF_EXAMPLES: Record<AssetType, string> = {
  blurb: "e.g. Why this book still matters today; use the strongest quote",
  social_post: "e.g. Make people curious about the book's central idea, with a short quote",
  social_reply: "e.g. Agree partly, but add the book's view that both sides can be combined",
  video_script: "e.g. Why this old book still answers today's problem; end with a question to comment on",
  youtube_video: "e.g. A 8-minute video explaining the book's central idea for beginners",
  newsletter: "e.g. Introduce the book to readers interested in housing and city life; call to action: read chapter I",
  ad_copy: "e.g. Ads for people frustrated with expensive city rents",
  lead_magnet: "e.g. A free guide with 5 ideas from the book for better neighbourhoods",
  persona: "e.g. The ideal reader of this book among today's professionals",
};

/**
 * Form for grounded (RAG) generation plus the list of grounded assets, newest first.
 * Options adapt to the asset type: social posts, replies and video scripts choose a platform (which
 * decides length and style), other types a length; replies take the post to answer plus an optional
 * angle, all other types a brief (with an example that fits the type). With a book selected, it
 * generates from that book only and lists only that book's assets. The list shows the selected asset
 * type only ("Show all types" lifts that), and switching the type clears the brief and the pasted post,
 * so nothing written for another type is carried over.
 * @param refresh Changing it reloads the asset list.
 * @param bookId Only use (and list assets of) this book; null = all books.
 * @param onChange Called after generating (and after editing or deleting an asset) to refresh the app.
 */
export default function GroundedGenerator({ refresh, bookId, onChange }: {
  refresh: number; bookId: string | null; onChange: () => void;
}) {
  const assets = useApi(`assets:${refresh}`, api.listAssets);
  const [assetType, setAssetType] = useState<AssetType>("blurb"); // decides which fields are shown
  const [allTypes, setAllTypes] = useState(false); // list assets of every type, not only the selected one
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isReply = assetType === "social_reply";

  /** Form submit: request a grounded asset with the chosen type, options and brief (or post + angle). */
  async function submit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const get = (k: string) => String(f.get(k) ?? "").trim();
    setPending(true);
    setError(null);
    try {
      await api.generate({
        asset_type: assetType,
        brief: get("brief"),
        grounded: true,
        tone: (get("tone") || "neutral") as Tone,
        audience: get("audience"),
        humanize: Number(get("humanize") || 60),
        ...(bookId ? { source_ids: [bookId] } : {}),
        ...(usesPlatform(assetType) ? { platform: get("platform") as Platform } : { length: get("length") as Length }),
        ...(isReply ? { reply_to: get("reply_to") } : {}),
      });
      onChange();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setPending(false);
    }
  }

  // The server returns assets oldest first; show only grounded ones (of the selected book), newest on top,
  // and of those only the selected type unless "Show all types" is on.
  const grounded = (assets.data ?? [])
    .filter((a) => a.grounded && (!bookId || a.source_ids.includes(bookId)))
    .reverse();
  const shown = allTypes ? grounded : grounded.filter((a) => a.asset_type === assetType);
  const typeLabel = assetTypeLabel(assetType).replace(/\s*\(.*\)$/, ""); // "YouTube video page (titles · …)" → "YouTube video page"

  return (
    <div className="bc-stack" style={{ gap: 16 }}>
      <SectionHeading icon={Sparkles} title="Grounded asset generator" count={shown.length}>
        {grounded.length > 0 && (
          <Button size="sm" variant="ghost" onClick={() => setAllTypes(!allTypes)}
            title={allTypes ? `List only ${typeLabel} assets` : "List the assets of every type"}>
            {allTypes ? `Only ${typeLabel}` : `Show all types (${grounded.length})`}
          </Button>
        )}
      </SectionHeading>
      <Card>
        <form className="bc-stack" onSubmit={submit}>
          <Field name="asset_type" as="select" label="Asset type" options={[...ASSET_TYPES, ...PLANNED_ASSET_TYPES]}
            onChange={(value) => setAssetType(value as AssetType)} />
          <div className="bc-row" style={{ gap: 12, alignItems: "flex-start" }}>
            <div style={{ flex: 1, minWidth: 140 }}>
              {usesPlatform(assetType)
                ? <Field name="platform" as="select" label="Platform" options={PLATFORMS} />
                : <Field name="length" as="select" label="Length" options={LENGTHS} defaultValue="standard" />}
            </div>
            <div style={{ flex: 1, minWidth: 140 }}>
              <Field name="tone" as="select" label="Tone" options={TONES} />
            </div>
          </div>
          <Field name="audience" label="Target audience (optional)" placeholder="e.g. young urban planners" />
          <RangeField name="humanize" label="How human should it sound?" defaultValue={60} describe={humanizeLabel}
            hint="Higher = less typical AI wording. From 60 on, AI clichés found in the result are rewritten automatically." />
          {isReply && (
            <Field name="reply_to" as="textarea" label="Their post" rows={5} required
              placeholder="Paste the post you want to reply to" />
          )}
          {/* key: a new asset type starts with an empty brief instead of the text written for the previous type. */}
          <Field key={`brief-${assetType}`} name="brief" as="textarea" label={isReply ? "Your angle (optional)" : "Brief"}
            rows={3} placeholder={BRIEF_EXAMPLES[assetType]} required={!isReply} />
          <Button type="submit" icon={Sparkles} loading={pending}>
            {pending ? "Generating…" : isReply ? "Generate reply from sources" : "Generate from sources"}
          </Button>
          {error && <ErrorNote>{error}</ErrorNote>}
        </form>
      </Card>
      {assets.error ? (
        <ErrorNote>{assets.error}</ErrorNote>
      ) : shown.length ? (
        shown.map((a) => <AssetCard key={a.id} asset={a} onChange={onChange} />)
      ) : (
        <Placeholder icon={Sparkles}>
          {assets.loading ? "Loading…"
            : allTypes || !grounded.length ? "Grounded assets with citations will appear here."
            : `No ${typeLabel} yet${bookId ? " for this book" : ""}. Generate one above, or show all types.`}
        </Placeholder>
      )}
    </div>
  );
}
