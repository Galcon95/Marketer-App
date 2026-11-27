"use client";

/**
 * The user manual (/help): loaded from the server (GET /help/manual, the single source in server/help/manual.md,
 * also read by "Ask the app"), with a table of contents of its sections. Open without signing in (proxy.ts
 * PUBLIC_PATHS). A link like /help#connect-your-youtube-channel scrolls to that section once the text is there.
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import Markdown from "@/components/Markdown";
import LegalFooter from "@/components/LegalFooter";
import { API_URL } from "@/lib/api";
import { parseMarkdown } from "@/lib/markdown";

export default function HelpPage() {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch(`${API_URL}/help/manual`)
      .then((res) => (res.ok ? res.text() : Promise.reject(new Error(String(res.status)))))
      .then(setText)
      .catch(() => setError(true));
  }, []);

  useEffect(() => { // the text arrived: now the section of the link's #anchor exists
    const id = decodeURIComponent(window.location.hash.slice(1));
    if (text && id) document.getElementById(id)?.scrollIntoView();
  }, [text]);

  const sections = text ? parseMarkdown(text).filter((b) => b.kind === "heading" && b.level === 2) : [];

  return (
    <div className="bc-root legal-page help-page">
      <div className="help-layout">
        <nav className="help-toc" aria-label="Sections">
          <Link href="/" className="help-back">← Back to the app</Link>
          {sections.map((s) => s.kind === "heading" && <a key={s.id} href={`#${s.id}`}>{s.text}</a>)}
        </nav>
        <article className="legal-text help-text">
          {error && <p>The manual cannot be loaded right now (the server does not answer). Please try again later.</p>}
          {!error && text === null && <p className="bc-hint">Loading the manual…</p>}
          {text && <Markdown text={text} />}
        </article>
      </div>
      <LegalFooter />
    </div>
  );
}
