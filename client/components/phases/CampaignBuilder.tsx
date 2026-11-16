"use client";

/**
 * Campaign Builder, the "Campaign kit" tab of the Content Studio (Phase 2): a book brief (pre-filled from a
 * library book and its summary) becomes a zero-shot campaign kit of 3 reader personas, 5 social posts and a blurb (POST /campaigns). Past
 * campaigns are listed below, the newest open.
 */

import { useState, type SubmitEvent } from "react";
import { BookOpen, Check, ChevronDown, ChevronRight, FileText, Megaphone, Sparkles, Trash2, Users, Wand2 } from "lucide-react";
import { api, bookTitle, errorMessage, humanizeLabel, type Asset, type CampaignSummary, type Source } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import AssetCard from "../AssetCard";
import { formatUsd } from "../UsagePanel";
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
/**
 * Title and author of a library book: "Garden-Cities_Ebenezer-Howard.pdf" → ["Garden Cities", "Ebenezer Howard"].
 * Without an author part in the file name, the author from the PDF's metadata is used ("" if the PDF names none).
 */
function splitTitle(source: Source): [title: string, author: string] {
  const [title, author = ""] = bookTitle(source.filename).split(" — ");
  return [title, author || source.author];
}

/** Name of a persona asset: the first line up to " — " (as written by the campaign kit), at most 60 characters. */
function personaName(asset: Asset) {
  return asset.text.split("\n")[0].split(" — ")[0].replace(/^name:\s*/i, "").trim().slice(0, 60);
}

/**
 * The brief form. Picking a library book fills title, author, themes (from its summary) and the hook
 * (first paragraph of the summary); everything stays editable. The model sees only this brief.
 * Fields are uncontrolled and re-mounted (key) when the book or its summary changes.
 */
function BriefForm({ books, refresh, onDone }: { books: Source[]; refresh: number; onDone: () => void }) {
  const [bookId, setBookId] = useState<string>(books[0]?.id ?? NEW_BOOK);
  const book = books.find((b) => b.id === bookId);
  const summary = useApi(`campaign-summary:${bookId}`, () => (book ? api.getSummary(book.id) : Promise.resolve(null)));
  const s = summary.loading ? null : summary.data; // useApi keeps the previous book's summary while loading
  const [title, bookAuthor] = book ? splitTitle(book) : ["", ""];
  const themes = s?.themes ?? [];
  const [picked, setPicked] = useState<string[] | null>(null); // null = default (first three themes)
  const chosen = picked ?? themes.slice(0, 3);
  const [audience, setAudience] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Personas made for this book before (kits or the Knowledge Hub), offered as audience focus: only these are
  // loaded, not every asset of the project.
  const bookPersonas = useApi(book ? `campaign-personas:${book.id}:${refresh}` : null,
    () => api.listAssets({ asset_type: "persona", source_id: book!.id }));
  const personas = [...new Set((bookPersonas.data ?? []).map(personaName))].filter(Boolean);

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

  /** Form submit: send the brief to POST /campaigns. */
  async function submit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const get = (k: string) => String(f.get(k) ?? "").trim();
    const author = get("author");
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
          <Field name="author" label="Author / pen name" defaultValue={bookAuthor} placeholder="e.g. Jane Doe" />
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
            hint="Higher = less typical AI wording. From 60 on, every post goes through the humanizer; the blurb when AI clichés are found." />
        </div>

        <Button type="submit" icon={Sparkles} loading={pending}>{pending ? "Writing personas, posts and blurb…" : "Generate campaign (zero-shot)"}</Button>
        <span className="bc-hint">
          {pending ? "Takes about 20-40 seconds." : "3 personas → 5 posts + 1 blurb · POST /projects/{id}/campaigns"}
        </span>
        {error && <ErrorNote>{error}</ErrorNote>}
      </form>
    </Card>
  );
}

/** How many campaign rows are loaded at first and with each "Show more". */
const PAGE = 10;

/**
 * The assets of one opened campaign kit, loaded only now (GET /campaigns/{id}): personas, posts, blurb.
 * @param campaignId The kit to load.
 * @param refresh Changing it reloads the kit (after an edit or delete).
 * @param onChange Reload after an edit or delete.
 */
function CampaignAssets({ campaignId, refresh, onChange }: { campaignId: string; refresh: number; onChange: () => void }) {
  const kit = useApi(`campaign:${campaignId}:${refresh}`, () => api.getCampaign(campaignId));
  if (kit.error) return <ErrorNote>{kit.error}</ErrorNote>;
  if (!kit.data) return <Placeholder icon={Wand2}>Loading the campaign…</Placeholder>;
  const assets: Asset[] = kit.data;
  const personas = assets.filter((a) => a.asset_type === "persona");
  const posts = assets.filter((a) => a.asset_type === "social_post");
  const blurbs = assets.filter((a) => a.asset_type === "blurb");
  return (
    <div className="bc-stack">
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
 * One campaign kit as a row (cover, title, date, assets, tokens, Delete). Its assets are loaded and drawn only
 * while it is open, so a long list of kits stays light.
 * @param campaign The kit's summary from GET /campaigns.
 * @param defaultOpen Open at first (the newest kit).
 * @param refresh Changing it reloads the open kit.
 * @param onChange Reload after an edit or delete.
 */
function CampaignRow({ campaign, defaultOpen, refresh, onChange }: {
  campaign: CampaignSummary; defaultOpen: boolean; refresh: number; onChange: () => void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { title, asset_count: count } = campaign;

  /** Delete the whole kit (all its assets) after a confirmation, then reload. */
  async function remove() {
    if (!window.confirm(`Delete the whole campaign "${title}" with all ${count} assets? This cannot be undone.`)) return;
    setDeleting(true);
    setError(null);
    try {
      await api.deleteCampaign(campaign.campaign_id);
      onChange();
    } catch (err) {
      setError(errorMessage(err));
      setDeleting(false);
    }
  }

  return (
    <div className="bc-card bc-campaign">
      <div className="bc-row bc-campaign-head">
        <button type="button" className="bc-campaign-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? <ChevronDown size={16} aria-hidden /> : <ChevronRight size={16} aria-hidden />}
          {campaign.source_id && <BookCover sourceId={campaign.source_id} title={title} width={28} />}
          <span style={{ minWidth: 0 }}>
            <strong>{title}</strong>
            <span className="bc-hint" style={{ display: "block" }}>
              {new Date(campaign.created_at).toLocaleString()} · {count} assets · {campaign.tokens.toLocaleString()} tokens
              {campaign.cost != null && ` · ${formatUsd(campaign.cost)}`}
              {campaign.audience && ` · focus: ${campaign.audience}`}
            </span>
          </span>
        </button>
        <Button size="sm" variant="ghost" icon={Trash2} loading={deleting} onClick={remove}
          title={`Delete this campaign and all ${count} of its assets`}>
          Delete
        </Button>
      </div>
      {error && <ErrorNote>{error}</ErrorNote>}
      {open && <div className="bc-campaign-body"><CampaignAssets campaignId={campaign.campaign_id} refresh={refresh} onChange={onChange} /></div>}
    </div>
  );
}

/**
 * Campaign kit (Content Studio, Phase 2): one book brief → a zero-shot campaign kit (POST /campaigns):
 * 3 reader personas, 5 social posts written for them, 1 blurb. No excerpts from the book are used;
 * the grounded generator (the "Single asset" tab) is the counterpart that writes from the book's text.
 * Left: the brief, pre-filled from the library. Right: the kits as rows, newest first, PAGE at a time
 * ("Show more"); a kit's assets are loaded only when it is opened (the newest is open). Plus earlier single
 * zero-shot assets.
 * @param refresh Counter from AppShell; changing it reloads books and assets.
 * @param onChange Call after generating, editing or deleting so the whole app refreshes.
 */
export default function CampaignBuilder({ refresh, onChange }: { refresh: number; onChange: () => void }) {
  const sources = useApi(`sources:${refresh}`, api.listSources);
  const books = (sources.data ?? []).filter((s) => s.status === "ready" && s.kind === "document");
  // The newest `shown` kits as summary rows; "Show more" loads the next PAGE. Kits' texts load when one is opened.
  const [shown, setShown] = useState(PAGE);
  const campaigns = useApi(`campaigns:${refresh}:${shown}`, () => api.listCampaigns(shown));
  const page = campaigns.data;
  // Zero-shot assets outside any kit, made by the old single-asset form (only these, not every asset).
  const singleAssets = useApi(`zero-shot-singles:${refresh}`, () => api.listAssets({ grounded: false, in_campaign: false }));
  const singles = [...(singleAssets.data ?? [])].reverse();

  return (
    <div className="bc-split">
      {sources.data ? <BriefForm books={books} refresh={refresh} onDone={onChange} /> : (
        <Card title="Campaign brief" icon={FileText}>
          {sources.error ? <ErrorNote>{sources.error}</ErrorNote> : <Placeholder icon={FileText}>Loading books…</Placeholder>}
        </Card>
      )}

      <div className="bc-stack">
        <SectionHeading icon={Wand2} title="Campaigns" count={page?.total}>
          <Badge icon={Sparkles}>Zero-shot · no book excerpts</Badge>
        </SectionHeading>
        {campaigns.error ? (
          <ErrorNote>{campaigns.error}</ErrorNote>
        ) : page?.items.length ? (
          <>
            {page.items.map((c, i) => (
              <CampaignRow key={c.campaign_id} campaign={c} defaultOpen={i === 0} refresh={refresh} onChange={onChange} />
            ))}
            {page.total > page.items.length && (
              <Button variant="ghost" loading={campaigns.loading} onClick={() => setShown(shown + PAGE)}>
                Show {Math.min(PAGE, page.total - page.items.length)} more ({page.items.length} of {page.total})
              </Button>
            )}
          </>
        ) : (
          <Placeholder icon={Wand2}>{campaigns.loading ? "Loading…" : "No campaign yet. Pick a book, check the brief and press Generate."}</Placeholder>
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
