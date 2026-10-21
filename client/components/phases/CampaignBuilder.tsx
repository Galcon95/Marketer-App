"use client";

import { useState, type SubmitEvent } from "react";
import { BookOpen, Check, FileText, Megaphone, Sparkles, Users, Wand2 } from "lucide-react";
import { api, bookTitle, errorMessage, humanizeLabel, PROJECT_ID, type Asset, type Source } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import AssetCard from "../AssetCard";
import BookCover from "../BookCover";
import { Badge, Button, Card, ErrorNote, Field, Placeholder, RangeField, SectionHeading } from "../ui";

/** Book-picker value for a book that is not in the library yet (pre-launch). */
const NEW_BOOK = "__new";
/** Audience-select value that shows a free-text field. */
const CUSTOM_AUDIENCE = "__custom";
/** Preset audience focuses offered for every book. */
const AUDIENCE_PRESETS = ["Book clubs", "BookTok / Bookstagram readers", "Newsletter subscribers", "Students and teachers", "Professionals in the field"];
/** Genre suggestions for the genre field (free text is allowed too). */
const GENRES = [
  "Non-fiction · history", "Non-fiction · economics", "Non-fiction · business", "Non-fiction · urban planning",
  "Self-help · productivity", "Biography / memoir", "Popular science", "Literary fiction", "Cozy mystery",
  "Thriller", "Romance", "Fantasy", "Science fiction", "Historical fiction",
];
/** localStorage key of the author name typed last (books whose file name has no author). */
const AUTHOR_KEY = "campaign.author";

/** Read the remembered author name; "" if none or storage is blocked. */
function rememberedAuthor() {
  try {
    return localStorage.getItem(AUTHOR_KEY) ?? "";
  } catch {
    return "";
  }
}

/**
 * Title and author of a library book from its file name: "Garden-Cities_Ebenezer-Howard.pdf" →
 * ["Garden Cities", "Ebenezer Howard"]; without an author part, the author is "".
 */
function splitTitle(source: Source): [title: string, author: string] {
  const [title, author = ""] = bookTitle(source.filename).split(" — ");
  return [title, author];
}

/** Name of a persona asset: the first line up to " — " (as written by the campaign kit), at most 60 characters. */
function personaName(asset: Asset) {
  return asset.text.split("\n")[0].split(" — ")[0].replace(/^name:\s*/i, "").trim().slice(0, 60);
}

/** Book title from a campaign brief ('Book: "Title" by Author' on the first line). */
function briefTitle(brief: string) {
  return /^Book: "([^"]+)"/.exec(brief)?.[1] ?? "Campaign";
}

/**
 * The brief form. Picking a library book fills title, author, themes (from its summary) and the hook
 * (first paragraph of the summary); everything stays editable. The model sees only this brief.
 * Fields are uncontrolled and re-mounted (key) when the book or its summary changes.
 */
function BriefForm({ books, assets, onDone }: { books: Source[]; assets: Asset[]; onDone: () => void }) {
  const [bookId, setBookId] = useState<string>(books[0]?.id ?? NEW_BOOK);
  const book = books.find((b) => b.id === bookId);
  const summary = useApi(`campaign-summary:${bookId}`, () => (book ? api.getSummary(book.id) : Promise.resolve(null)));
  const s = summary.loading ? null : summary.data; // useApi keeps the previous book's summary while loading
  const [title, fileAuthor] = book ? splitTitle(book) : ["", ""];
  const themes = s?.themes ?? [];
  const [picked, setPicked] = useState<string[] | null>(null); // null = default (first three themes)
  const chosen = picked ?? themes.slice(0, 3);
  const [audience, setAudience] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Personas made for this book before (kits or the Knowledge Hub), offered as audience focus.
  const personas = [...new Set(assets.filter((a) => a.asset_type === "persona" && book && a.source_ids.includes(book.id)).map(personaName))].filter(Boolean);

  /** Switch the book: reset theme choice and audience; the fields re-mount with the new defaults. */
  function pickBook(id: string) {
    setBookId(id);
    setPicked(null);
    setAudience("");
  }

  /** Toggle a theme chip. */
  function toggleTheme(theme: string) {
    setPicked(chosen.includes(theme) ? chosen.filter((t) => t !== theme) : [...chosen, theme]);
  }

  /** Form submit: send the brief to POST /campaigns and remember the author for next time. */
  async function submit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const get = (k: string) => String(f.get(k) ?? "").trim();
    const author = get("author");
    try {
      if (author) localStorage.setItem(AUTHOR_KEY, author);
    } catch { /* storage blocked: just don't remember */ }
    setPending(true);
    setError(null);
    try {
      await api.createCampaign({
        title: get("title"), author, genre: get("genre"), themes: chosen, premise: get("premise"),
        comparables: get("comparables"), audience: audience === CUSTOM_AUDIENCE ? get("audience_custom") : audience,
        humanize: Number(get("humanize") || 60), source_id: book?.id ?? null,
      });
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setPending(false);
    }
  }

  const formKey = `${bookId}:${s ? "summary" : "none"}`; // re-mount the fields when their defaults change
  return (
    <Card title="Campaign brief" icon={FileText}>
      <form className="bc-stack" onSubmit={submit}>
        <div className="bc-field">
          <label className="bc-label" htmlFor="f-book">Book</label>
          <div className="bc-row" style={{ gap: 12, flexWrap: "nowrap" }}>
            {book ? <BookCover sourceId={book.id} title={title} width={40} link /> : (
              <div style={{ width: 40, height: 60, display: "grid", placeItems: "center", border: "1px dashed var(--border)", borderRadius: "var(--radius-sm)", color: "var(--ink-muted)", flexShrink: 0 }}>
                <BookOpen size={16} aria-hidden />
              </div>
            )}
            <Field name="book" as="select" defaultValue={bookId} onChange={pickBook}
              options={[...books.map((b) => ({ value: b.id, label: bookTitle(b.filename) })), { value: NEW_BOOK, label: "New book (not in the library)" }]} />
          </div>
        </div>

        <div key={formKey} className="bc-stack">
          {book ? <input type="hidden" name="title" value={title} /> : (
            <Field name="title" label="Title" placeholder="e.g. The Quiet Harbour" required />
          )}
          <Field name="author" label="Author / pen name" defaultValue={fileAuthor || rememberedAuthor()} placeholder="e.g. Jane Doe" />
          <div className="bc-field">
            <label className="bc-label" htmlFor="f-genre">Genre</label>
            <input id="f-genre" name="genre" className="bc-input" list="genre-list" placeholder="e.g. Cozy mystery" autoComplete="off" />
            <datalist id="genre-list">{GENRES.map((g) => <option key={g} value={g} />)}</datalist>
          </div>

          {themes.length > 0 && (
            <div className="bc-field">
              <span className="bc-label">Themes to build on</span>
              <div className="bc-row" style={{ gap: 6 }}>
                {themes.map((t) => {
                  const on = chosen.includes(t);
                  return (
                    <Button key={t} type="button" size="sm" variant={on ? "primary" : "secondary"} icon={on ? Check : undefined}
                      aria-pressed={on} onClick={() => toggleTheme(t)}>{t}</Button>
                  );
                })}
              </div>
              <span className="bc-hint">From the book summary.</span>
            </div>
          )}

          <Field name="premise" as="textarea" label="Hook / premise" rows={5} required
            defaultValue={s?.summary.split(/\n\s*\n/)[0] ?? ""}
            placeholder="What is the book about, and why should someone read it? A few sentences."
            hint={book && !s && !summary.loading
              ? "This book has no summary yet. Create one in the Knowledge Hub to pre-fill hook and themes, or write it yourself."
              : s ? "Pre-filled from the book summary. The model sees only this brief, not the book." : undefined} />
          <Field name="comparables" label="For fans of (optional)" placeholder="e.g. Jane Jacobs, Lewis Mumford" />
        </div>

        {/* Outside the block above: keeps the chosen audience when the summary arrives; re-mounts per book. */}
        <div key={bookId} className="bc-stack">
          <Field name="audience_select" as="select" label="Audience focus" defaultValue="" onChange={setAudience}
            options={[
              { value: "", label: "General readers" },
              ...personas.map((p) => ({ value: p, label: `Persona: ${p}` })),
              ...AUDIENCE_PRESETS,
              { value: CUSTOM_AUDIENCE, label: "Other…" },
            ]}
            hint="The three personas are built around this focus." />
          {audience === CUSTOM_AUDIENCE && <Field name="audience_custom" placeholder="e.g. retired engineers who like local history" required />}

          <RangeField name="humanize" label="How human should it sound?" defaultValue={60} describe={humanizeLabel}
            hint="Higher = less typical AI wording. From 60 on, AI clichés found in the posts and blurb are rewritten automatically." />
        </div>

        <Button type="submit" icon={Sparkles} loading={pending}>{pending ? "Writing personas, posts and blurb…" : "Generate campaign (zero-shot)"}</Button>
        <span className="bc-hint">
          {pending ? "Takes about 20-40 seconds." : `3 personas → 5 posts + 1 blurb · POST /projects/${PROJECT_ID}/campaigns`}
        </span>
        {error && <ErrorNote>{error}</ErrorNote>}
      </form>
    </Card>
  );
}

/**
 * One campaign kit: header (cover, title, date, tokens) and its personas, posts and blurb.
 * @param assets The kit's assets in generation order.
 * @param onChange Reload after an edit or delete.
 */
function CampaignKit({ assets, onChange }: { assets: Asset[]; onChange: () => void }) {
  const personas = assets.filter((a) => a.asset_type === "persona");
  const posts = assets.filter((a) => a.asset_type === "social_post");
  const blurbs = assets.filter((a) => a.asset_type === "blurb");
  const first = assets[0];
  const sourceId = first.source_ids[0];
  const title = briefTitle(first.brief);
  return (
    <div className="bc-stack">
      <div className="bc-row" style={{ gap: 12 }}>
        {sourceId && <BookCover sourceId={sourceId} title={title} width={32} link />}
        <div style={{ minWidth: 0 }}>
          <strong>{title}</strong>
          <div className="bc-hint">
            {new Date(first.created_at).toLocaleString()} · {assets.reduce((n, a) => n + a.tokens, 0).toLocaleString()} tokens
            {first.audience && ` · focus: ${first.audience}`}
          </div>
        </div>
      </div>
      {personas.length > 0 && (
        <>
          <SectionHeading icon={Users} title="Reader personas" count={personas.length} />
          <div className="bc-grid bc-g3">{personas.map((a) => <AssetCard key={a.id} asset={a} onChange={onChange} />)}</div>
        </>
      )}
      {posts.length > 0 && (
        <>
          <SectionHeading icon={Megaphone} title="Social posts" count={posts.length} />
          <div className="bc-stack">{posts.map((a) => <AssetCard key={a.id} asset={a} onChange={onChange} />)}</div>
        </>
      )}
      {blurbs.length > 0 && (
        <>
          <SectionHeading icon={BookOpen} title="Blurb" />
          {blurbs.map((a) => <AssetCard key={a.id} asset={a} onChange={onChange} />)}
        </>
      )}
    </div>
  );
}

/**
 * Phase 2 (Campaign Builder): one book brief → a zero-shot campaign kit (POST /campaigns):
 * 3 reader personas, 5 social posts written for them, 1 blurb. No excerpts from the book are used;
 * the Knowledge Hub's grounded generator is the counterpart that writes from the book's text.
 * Left: the brief, pre-filled from the library. Right: the kits, newest first (older ones collapsed),
 * plus earlier single zero-shot assets.
 * @param refresh Counter from AppShell; changing it reloads books and assets.
 * @param onChange Call after generating, editing or deleting so the whole app refreshes.
 */
export default function CampaignBuilder({ refresh, onChange }: { refresh: number; onChange: () => void }) {
  const sources = useApi(`sources:${refresh}`, api.listSources);
  const assets = useApi(`assets:${refresh}`, api.listAssets);
  const books = (sources.data ?? []).filter((s) => s.status === "ready" && s.kind === "document");
  const all = assets.data ?? [];

  // Group the kits by campaign id (assets come oldest first), newest kit first.
  const kits = new Map<string, Asset[]>();
  for (const a of all) if (a.campaign_id) kits.set(a.campaign_id, [...(kits.get(a.campaign_id) ?? []), a]);
  const campaigns = [...kits.values()].reverse();
  const singles = all.filter((a) => !a.grounded && !a.campaign_id).reverse(); // made by the old single-asset form

  return (
    <div className="bc-split">
      {sources.data ? <BriefForm books={books} assets={all} onDone={onChange} /> : (
        <Card title="Campaign brief" icon={FileText}>
          {sources.error ? <ErrorNote>{sources.error}</ErrorNote> : <Placeholder icon={FileText}>Loading books…</Placeholder>}
        </Card>
      )}

      <div className="bc-stack">
        <SectionHeading icon={Wand2} title="Campaigns" count={campaigns.length}>
          <Badge icon={Sparkles}>Zero-shot · no book excerpts</Badge>
        </SectionHeading>
        {assets.error ? (
          <ErrorNote>{assets.error}</ErrorNote>
        ) : campaigns.length ? (
          campaigns.map((kit, i) => i === 0 ? (
            <CampaignKit key={kit[0].campaign_id} assets={kit} onChange={onChange} />
          ) : (
            <details key={kit[0].campaign_id} className="bc-card" style={{ padding: "12px 16px" }}>
              <summary style={{ cursor: "pointer" }}>
                <strong>{briefTitle(kit[0].brief)}</strong>{" "}
                <span className="bc-hint">{new Date(kit[0].created_at).toLocaleString()} · {kit.length} assets</span>
              </summary>
              <div style={{ marginTop: 16 }}><CampaignKit assets={kit} onChange={onChange} /></div>
            </details>
          ))
        ) : (
          <Placeholder icon={Wand2}>{assets.loading ? "Loading…" : "No campaign yet. Pick a book, check the brief and press Generate."}</Placeholder>
        )}
        {singles.length > 0 && (
          <details className="bc-card" style={{ padding: "12px 16px" }}>
            <summary style={{ cursor: "pointer" }}><strong>Earlier single assets</strong> <span className="bc-hint">{singles.length}</span></summary>
            <div className="bc-stack" style={{ marginTop: 16 }}>{singles.map((a) => <AssetCard key={a.id} asset={a} onChange={onChange} />)}</div>
          </details>
        )}
      </div>
    </div>
  );
}
