"use client";

/**
 * "Write a new post" in the "My Facebook Page" tab (Discussion Relevance Agent; admin only): a post or a question for
 * the readers, written from the book (POST /generate, grounded, platform Facebook) and published on the Page from the
 * same place, without going to the Content Studio. Below the form: the posts written here in this visit (also once
 * published, with their link) and older drafts that were never published. Each is an AssetCard, so Edit, Verify,
 * Copy, Delete and "Publish to my Facebook Page" work as in the Content Studio.
 */

import { useState, type SubmitEvent } from "react";
import { PenLine, Sparkles, X } from "lucide-react";
import { api, errorMessage, isFacebookPost, TONES, type Asset, type FacebookStatus, type Tone } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import AssetCard from "./AssetCard";
import { Button, ErrorNote, Field } from "./ui";

/** What kind of post to write: a normal post, or a question that invites comments. */
const KINDS = [
  { value: "social_post", label: "Post about the book" },
  { value: "reader_question", label: "Question for my readers" },
];
const BRIEFS: Record<string, string> = {
  social_post: "e.g. Make people curious about how industry would work without profit; use a short quote",
  reader_question: "e.g. Would you still work if you didn't have to? Ask readers what they think",
};
const MAX_DRAFTS = 3; // older unpublished drafts shown under the form

/**
 * The form and the posts written with it.
 * @param bookId The book to write from (null = all books).
 * @param facebook The Page's status, for the Publish button.
 * @param onChange Called after a post was written, edited, deleted or published, to refresh the app.
 */
export default function FacebookNewPost({ bookId, facebook, onChange }: {
  bookId: string | null; facebook: FacebookStatus; onChange: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState("social_post");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [written, setWritten] = useState<string[]>([]); // ids of the posts written here in this visit, newest first
  const assets = useApi(`facebook-drafts:${nonce}`, api.listAssets);

  /** After a change to a post: reload the list here and refresh the app. */
  function changed() {
    setNonce((n) => n + 1);
    onChange();
  }

  /** Form submit: write the post from the book. */
  async function submit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setPending(true);
    setError(null);
    try {
      const asset = await api.generate({
        asset_type: kind as Asset["asset_type"],
        brief: String(f.get("brief") ?? "").trim(),
        grounded: true,
        tone: (String(f.get("tone") ?? "") || "neutral") as Tone,
        ...(kind === "social_post" ? { platform: "facebook" as const } : {}),
        ...(bookId ? { source_ids: [bookId] } : {}),
      });
      setWritten((ids) => [asset.id, ...ids]);
      changed();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setPending(false);
    }
  }

  // Posts written here (newest first, published or not), then older drafts of this book that were never published.
  const all = (assets.data ?? []).filter((a) => isFacebookPost(a) && a.grounded && (!bookId || a.source_ids.includes(bookId)));
  const byId = new Map(all.map((a) => [a.id, a]));
  const mine = written.map((id) => byId.get(id)).filter((a): a is Asset => !!a);
  const drafts = all.filter((a) => !a.published_url && !written.includes(a.id)).reverse().slice(0, MAX_DRAFTS);

  return (
    <div className="bc-stack" style={{ gap: 12 }}>
      {open ? (
        <form className="bc-stack bc-cite-src" onSubmit={submit}
          style={{ borderLeft: 0, borderRadius: "var(--radius-md)", padding: 12, gap: 12 }}>
          <div className="bc-row" style={{ gap: 8, alignItems: "center" }}>
            <strong style={{ flex: 1 }}>New post on {facebook.page?.name ?? "your Page"}</strong>
            <Button size="sm" variant="ghost" icon={X} onClick={() => setOpen(false)} aria-label="Close the form">Close</Button>
          </div>
          <div className="bc-row" style={{ gap: 12, alignItems: "flex-start" }}>
            <div style={{ flex: 1, minWidth: 160 }}>
              <Field name="kind" as="select" label="Kind" options={KINDS} defaultValue={kind}
                onChange={(value) => setKind(value)} />
            </div>
            <div style={{ flex: 1, minWidth: 160 }}>
              <Field name="tone" as="select" label="Tone" options={TONES} />
            </div>
          </div>
          <Field key={`brief-${kind}`} name="brief" as="textarea" label="What should it be about?" rows={3} required
            placeholder={BRIEFS[kind]} />
          <div className="bc-row" style={{ gap: 8, alignItems: "center" }}>
            <Button type="submit" icon={Sparkles} loading={pending}>{pending ? "Writing…" : "Write from the book"}</Button>
            <span className="bc-hint" style={{ margin: 0 }}>Nothing is posted yet: you check the text first.</span>
          </div>
          {error && <ErrorNote>{error}</ErrorNote>}
        </form>
      ) : (
        <div className="bc-row" style={{ gap: 8, alignItems: "center" }}>
          <Button icon={PenLine} onClick={() => setOpen(true)}>Write a new post</Button>
          <span className="bc-hint" style={{ margin: 0 }}>A post or a question for your readers, written from the book.</span>
        </div>
      )}
      {assets.error && <ErrorNote>{assets.error}</ErrorNote>}
      {[...mine, ...drafts].map((a) => <AssetCard key={a.id} asset={a} onChange={changed} facebook={facebook} />)}
    </div>
  );
}
