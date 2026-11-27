/**
 * Shows a Markdown text parsed by lib/markdown.ts (the user manual). Headings get ids (their anchors), so
 * /help#some-section scrolls there. Links to other sites open in a new tab.
 */

import Link from "next/link";
import { Fragment } from "react";
import { parseMarkdown, type Inline } from "@/lib/markdown";

/** One line's pieces as React elements (always text: no HTML is ever rendered). `newTab`: every link opens in a
 * new tab (in the app's drawers, so the user's work stays where it is). */
function InlineText({ parts, newTab = false }: { parts: Inline[]; newTab?: boolean }) {
  return (
    <>
      {parts.map((p, i) => {
        if (p.kind === "bold") return <strong key={i}>{p.text}</strong>;
        if (p.kind === "italic") return <em key={i}>{p.text}</em>;
        if (p.kind === "code") return <code key={i}>{p.text}</code>;
        if (p.kind === "link") {
          return newTab || /^https?:\/\//.test(p.href)
            ? <a key={i} href={p.href} target="_blank" rel="noreferrer">{p.text}</a>
            : <Link key={i} href={p.href}>{p.text}</Link>;
        }
        return <Fragment key={i}>{p.text}</Fragment>;
      })}
    </>
  );
}

export default function Markdown({ text, newTab = false }: { text: string; newTab?: boolean }) {
  return (
    <>
      {parseMarkdown(text).map((block, i) => {
        switch (block.kind) {
          case "heading": {
            const Tag = (`h${block.level}`) as "h1" | "h2" | "h3";
            return <Tag key={i} id={block.id}>{block.text}</Tag>;
          }
          case "list": {
            const Tag = block.ordered ? "ol" : "ul";
            return <Tag key={i}>{block.items.map((item, j) => <li key={j}><InlineText parts={item} newTab={newTab} /></li>)}</Tag>;
          }
          case "tip":
            return <p key={i} className="md-tip"><InlineText parts={block.content} newTab={newTab} /></p>;
          default:
            return <p key={i}><InlineText parts={block.content} newTab={newTab} /></p>;
        }
      })}
    </>
  );
}
