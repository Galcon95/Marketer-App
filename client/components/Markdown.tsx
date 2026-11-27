/**
 * Shows a Markdown text parsed by lib/markdown.ts (the user manual). Headings get ids (their anchors), so
 * /help#some-section scrolls there. Links to other sites open in a new tab.
 */

import Link from "next/link";
import { Fragment } from "react";
import { parseMarkdown, type Inline } from "@/lib/markdown";

/** One line's pieces as React elements (always text: no HTML is ever rendered). */
function InlineText({ parts }: { parts: Inline[] }) {
  return (
    <>
      {parts.map((p, i) => {
        if (p.kind === "bold") return <strong key={i}>{p.text}</strong>;
        if (p.kind === "italic") return <em key={i}>{p.text}</em>;
        if (p.kind === "code") return <code key={i}>{p.text}</code>;
        if (p.kind === "link") {
          return /^https?:\/\//.test(p.href)
            ? <a key={i} href={p.href} target="_blank" rel="noreferrer">{p.text}</a>
            : <Link key={i} href={p.href}>{p.text}</Link>;
        }
        return <Fragment key={i}>{p.text}</Fragment>;
      })}
    </>
  );
}

export default function Markdown({ text }: { text: string }) {
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
            return <Tag key={i}>{block.items.map((item, j) => <li key={j}><InlineText parts={item} /></li>)}</Tag>;
          }
          case "tip":
            return <p key={i} className="md-tip"><InlineText parts={block.content} /></p>;
          default:
            return <p key={i}><InlineText parts={block.content} /></p>;
        }
      })}
    </>
  );
}
