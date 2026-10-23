"use client";

/**
 * The "Working on" bar (choose one book or all books) and readyBooks, the processed books of a source list.
 * Used by the Knowledge Hub ("Ask your book") and the Content Studio (the grounded generator).
 */

import { ChevronDown, Library } from "lucide-react";
import { bookTitle, type Source } from "@/lib/api";
import BookCover from "./BookCover";

/** The processed books of a project (ready PDFs and other documents), in upload order. */
export function readyBooks(sources: Source[]) {
  return sources.filter((s) => s.status === "ready" && s.kind === "document");
}

/**
 * "Working on" bar: choose one book or all books. The choice is shared by the whole app (AppShell holds it), so a
 * book picked in the Knowledge Hub is still picked in the Content Studio.
 * @param books The processed books.
 * @param selected Id of the selected book, or null for all books.
 * @param onSelect Called with the chosen book's id, or null for all books.
 * @param uses What uses the choice on this page, e.g. "Ask your book" (shown as a hint).
 */
export default function BookPicker({ books, selected, onSelect, uses }: {
  books: Source[]; selected: string | null; onSelect: (id: string | null) => void; uses: string;
}) {
  if (books.length === 0) return null;
  const book = books.find((b) => b.id === selected);
  return (
    <div className="bc-card" style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 16px", flexWrap: "wrap" }}>
      {book ? <BookCover sourceId={book.id} title={bookTitle(book.filename)} width={26} link /> : <Library size={18} className="bc-ico" aria-hidden />}
      <strong>Working on</strong>
      <div className="bc-select-wrap" style={{ minWidth: 260, flex: "0 1 420px" }}>
        <select className="bc-select" aria-label="Book to work on" value={selected ?? ""} onChange={(e) => onSelect(e.target.value || null)}>
          <option value="">All books ({books.length})</option>
          {books.map((b) => <option key={b.id} value={b.id}>{bookTitle(b.filename)}</option>)}
        </select>
        <ChevronDown size={16} className="bc-ico" aria-hidden />
      </div>
      <span className="bc-hint">{uses} {book ? "only this book" : "all books"}.</span>
    </div>
  );
}
