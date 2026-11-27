/**
 * A small Markdown parser for the app's own texts (the user manual, server/help/manual.md): headings (#, ##, ###),
 * paragraphs, "- " and "1. " lists, "> " tips, and inline **bold**, `code` and [links](url). Not a full Markdown
 * implementation on purpose: the texts are ours, and no extra package is needed. Anything else is shown as text.
 * Raw HTML is never rendered: everything becomes React text, so a manual can never inject markup.
 */

/** A piece of a line: plain text, bold, code or a link. */
export type Inline =
  | { kind: "text"; text: string }
  | { kind: "bold"; text: string }
  | { kind: "italic"; text: string }
  | { kind: "code"; text: string }
  | { kind: "link"; text: string; href: string };

/** A block of the document. */
export type Block =
  | { kind: "heading"; level: 1 | 2 | 3; text: string; id: string }
  | { kind: "paragraph"; content: Inline[] }
  | { kind: "list"; ordered: boolean; items: Inline[][] }
  | { kind: "tip"; content: Inline[] };

/**
 * A heading's anchor: lower case, letters and digits joined by "-". The same rule as the server's manual.anchor, so
 * links like /help#connect-your-youtube-channel (also from "Ask the app") open the right section.
 */
export function anchor(heading: string): string {
  return (heading.toLowerCase().match(/[a-z0-9]+/g) ?? []).join("-");
}

/** Split one line into text, **bold**, *italic*, `code` and [links](url). Links go only to http(s), / or # targets. */
export function parseInline(line: string): Inline[] {
  const out: Inline[] = [];
  const pattern = /\*\*(.+?)\*\*|(?<![\w*])\*(?!\s)([^*]+?)\*(?![\w*])|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)/g;
  let last = 0;
  for (const m of line.matchAll(pattern)) {
    if (m.index > last) out.push({ kind: "text", text: line.slice(last, m.index) });
    if (m[1] !== undefined) out.push({ kind: "bold", text: m[1] });
    else if (m[2] !== undefined) out.push({ kind: "italic", text: m[2] });
    else if (m[3] !== undefined) out.push({ kind: "code", text: m[3] });
    else if (/^(https?:\/\/|\/|#)/.test(m[5])) out.push({ kind: "link", text: m[4], href: m[5] });
    else out.push({ kind: "text", text: m[0] }); // e.g. javascript: links stay plain text
    last = m.index + m[0].length;
  }
  if (last < line.length) out.push({ kind: "text", text: line.slice(last) });
  return out;
}

/** The document's blocks. Consecutive text lines form one paragraph; a blank line ends a block. */
export function parseMarkdown(markdown: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  let tip: string[] = [];

  const flush = () => {
    if (paragraph.length) blocks.push({ kind: "paragraph", content: parseInline(paragraph.join(" ")) });
    if (list) blocks.push({ kind: "list", ordered: list.ordered, items: list.items.map(parseInline) });
    if (tip.length) blocks.push({ kind: "tip", content: parseInline(tip.join(" ")) });
    paragraph = [];
    list = null;
    tip = [];
  };

  for (const raw of markdown.replace(/<!--[\s\S]*?-->/g, "").split(/\r?\n/)) {
    const line = raw.trimEnd();
    const heading = /^(#{1,3}) +(.+)$/.exec(line);
    const bullet = /^ *(?:[-*]|(\d+)\.) +(.+)$/.exec(line);
    const quote = /^> ?(.*)$/.exec(line);
    if (!line.trim()) {
      flush();
    } else if (heading) {
      flush();
      const text = heading[2].trim();
      blocks.push({ kind: "heading", level: heading[1].length as 1 | 2 | 3, text, id: anchor(text) });
    } else if (bullet) {
      const ordered = bullet[1] !== undefined;
      if (!list || list.ordered !== ordered) {
        flush();
        list = { ordered, items: [] };
      }
      list.items.push(bullet[2]);
    } else if (quote) {
      if (!tip.length) flush();
      tip.push(quote[1]);
    } else if (list && /^ {2,}\S/.test(raw)) {
      list.items[list.items.length - 1] += " " + line.trim(); // a list item continued on the next line
    } else {
      if (list || tip.length) flush();
      paragraph.push(line.trim());
    }
  }
  flush();
  return blocks;
}
