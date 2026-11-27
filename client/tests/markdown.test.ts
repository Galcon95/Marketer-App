/**
 * Unit tests of the manual's small Markdown parser (lib/markdown.ts): blocks, inline parts, anchors that match the
 * server's (core/manual.py anchor), and that unsafe links stay text. Run with `npm test`.
 */
import { describe, expect, it } from "vitest";
import { anchor, parseInline, parseMarkdown } from "../lib/markdown";

describe("anchor", () => {
  it("is the heading in lower case, words joined by dashes (as on the server)", () => {
    expect(anchor("Connect your YouTube channel")).toBe("connect-your-youtube-channel");
    expect(anchor("Usage, limits & costs")).toBe("usage-limits-costs");
  });
});

describe("parseInline", () => {
  it("finds bold, code and links", () => {
    expect(parseInline("Press **Upload**, see `PDF` or [Help](/help#books).")).toEqual([
      { kind: "text", text: "Press " }, { kind: "bold", text: "Upload" }, { kind: "text", text: ", see " },
      { kind: "code", text: "PDF" }, { kind: "text", text: " or " }, { kind: "link", text: "Help", href: "/help#books" },
      { kind: "text", text: "." },
    ]);
  });
  it("finds italics, but not a lone star or stars inside words", () => {
    expect(parseInline("under *Pipeline*, 2 * 3 and a*b*c")).toEqual([
      { kind: "text", text: "under " }, { kind: "italic", text: "Pipeline" }, { kind: "text", text: ", 2 * 3 and a*b*c" },
    ]);
  });
  it("keeps a javascript: link as plain text", () => {
    expect(parseInline("[x](javascript:alert(1))")).toEqual([{ kind: "text", text: "[x](javascript:alert(1)" },
      { kind: "text", text: ")" }]);
  });
});

describe("parseMarkdown", () => {
  it("makes headings, paragraphs, lists and tips", () => {
    const blocks = parseMarkdown([
      "# Manual", "", "<!-- a note -->", "## Your books", "Upload a book", "as a PDF.", "",
      "1. Open the tab", "2. Press **Upload**", "   and wait", "", "- one", "- two", "", "> Tip: be patient.",
    ].join("\n"));
    expect(blocks.map((b) => b.kind)).toEqual(["heading", "heading", "paragraph", "list", "list", "tip"]);
    expect(blocks[1]).toEqual({ kind: "heading", level: 2, text: "Your books", id: "your-books" });
    expect(blocks[2]).toEqual({ kind: "paragraph", content: [{ kind: "text", text: "Upload a book as a PDF." }] });
    const ordered = blocks[3];
    expect(ordered.kind === "list" && ordered.ordered && ordered.items.length).toBe(2);
    expect(ordered.kind === "list" && ordered.items[1].at(-1)).toEqual({ kind: "text", text: " and wait" });
  });
});
