"use client";

/**
 * "My Substack" (Community, Scan Substack mode): the author's own Substack publication and its latest posts, read from
 * its public RSS feed by the server (GET /projects/{id}/substack; no login, no cost). The author enters the address
 * once (the publication, a post link or the profile link substack.com/@name); it is saved with the project, and Scan
 * Substack then leaves the author's own posts out.
 */

import { useState, type SubmitEvent } from "react";
import { ExternalLink, Pencil, X } from "lucide-react";
import { api, errorMessage, type SubstackFeed } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { Button, ErrorNote } from "./ui";

/** The box: the address form when none is saved (or while changing it), else the latest posts. */
export default function MySubstack() {
  const [version, setVersion] = useState(0);
  const feed = useApi(`substack:${version}`, api.substackFeed);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const data: SubstackFeed | undefined = feed.data;

  /** Save the address (the server checks that the publication's feed exists). */
  async function save(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    const address = String(new FormData(e.currentTarget).get("address") ?? "").trim();
    if (!address) return;
    setBusy(true);
    setError(null);
    try {
      await api.setSubstack(address);
      setEditing(false);
      setVersion((v) => v + 1);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  /** Forget the publication after confirmation. */
  async function forget() {
    if (!window.confirm("Forget your Substack in the app? Your posts on Substack stay as they are.")) return;
    try {
      await api.clearSubstack();
      setVersion((v) => v + 1);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const showForm = editing || (data && !data.publication);
  return (
    <div className="bc-stack" style={{ gap: 8, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
      <div className="bc-row" style={{ gap: 6, alignItems: "center" }}>
        <span className="bc-label" style={{ margin: 0 }}>My Substack</span>
        <span style={{ flex: 1 }} />
        {data?.publication && !editing && (
          <>
            <Button size="sm" variant="ghost" icon={Pencil} onClick={() => setEditing(true)} title="Change"
              aria-label="Change my Substack" />
            <Button size="sm" variant="ghost" icon={X} onClick={forget} title="Forget" aria-label="Forget my Substack" />
          </>
        )}
      </div>
      {feed.loading && !data && <span className="bc-hint">Loading your Substack…</span>}
      {feed.error && <ErrorNote>{feed.error}</ErrorNote>}
      {showForm && (
        <form className="bc-stack" style={{ gap: 6 }} onSubmit={save}>
          <input name="address" className="bc-input" required maxLength={300} defaultValue={data?.url ?? ""}
            aria-label="Your Substack address" placeholder="yourname.substack.com or substack.com/@yourname" />
          <div className="bc-row" style={{ gap: 6 }}>
            <Button type="submit" size="sm" loading={busy}>Save</Button>
            {editing && <Button size="sm" variant="ghost" onClick={() => setEditing(false)} disabled={busy}>Cancel</Button>}
          </div>
          <span className="bc-hint" style={{ margin: 0 }}>
            Optional. Shows your latest posts here, and Scan Substack leaves them out.
          </span>
        </form>
      )}
      {error && <ErrorNote>{error}</ErrorNote>}
      {data?.publication && !editing && (
        <>
          <a href={data.url} target="_blank" rel="noopener noreferrer" className="bc-hint" style={{ margin: 0 }}>
            {data.publication}.substack.com <ExternalLink size={12} aria-hidden />
          </a>
          {data.posts.length === 0 && <span className="bc-hint" style={{ margin: 0 }}>No posts yet.</span>}
          {data.posts.slice(0, 5).map((p) => (
            <div key={p.url} className="bc-stack" style={{ gap: 2 }}>
              <a href={p.url} target="_blank" rel="noopener noreferrer" style={{ fontWeight: 600, fontSize: 13 }}>
                {p.title}
              </a>
              <span className="bc-hint" style={{ margin: 0 }}>
                {p.published_at ? new Date(p.published_at).toLocaleDateString() : ""}
                {p.subtitle ? `${p.published_at ? " · " : ""}${p.subtitle}` : ""}
              </span>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
