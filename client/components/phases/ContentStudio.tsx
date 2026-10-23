"use client";

/**
 * Phase 2, Content Studio: everything that produces marketing content, in two tabs:
 *   Single asset   the grounded generator: one blurb, post, reply, script, newsletter, ... written from the books,
 *                  with citations, for the book chosen under "Working on"
 *   Campaign kit   the Campaign Builder: a book brief becomes 3 personas, 5 posts and a blurb (zero-shot)
 */

import { useState } from "react";
import { BookOpen, Megaphone } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import BookPicker, { readyBooks } from "../BookPicker";
import GroundedGenerator from "../GroundedGenerator";
import { Tabs, type TabItem } from "../ui";
import CampaignBuilder from "./CampaignBuilder";

/** The two ways of producing content. */
type StudioTab = "single" | "kit";

const STUDIO_TABS: TabItem<StudioTab>[] = [
  { id: "single", kicker: "FROM YOUR BOOKS", label: "Single asset", icon: BookOpen },
  { id: "kit", kicker: "ZERO-SHOT", label: "Campaign kit", icon: Megaphone },
];

/**
 * Phase 2: the Content Studio with its two tabs (see the file header).
 * @param refresh Changing it reloads books and assets.
 * @param onChange Called after generating, editing or deleting, to refresh the app.
 * @param bookId The book being worked on, shared across the app (null = all books).
 * @param onSelectBook Changes the book being worked on.
 */
export default function ContentStudio({ refresh, onChange, bookId: selectedBook, onSelectBook }: {
  refresh: number; onChange: () => void; bookId: string | null; onSelectBook: (id: string | null) => void;
}) {
  const [tab, setTab] = useState<StudioTab>("single");
  const sources = useApi(`studio-sources:${refresh}`, api.listSources);
  const books = readyBooks(sources.data ?? []);
  // The shared choice only counts while that book is ready (it may have been deleted or be re-indexing).
  const bookId = selectedBook && books.some((b) => b.id === selectedBook) ? selectedBook : null;

  return (
    <>
      <Tabs items={STUDIO_TABS} value={tab} onChange={setTab} />
      {tab === "single" ? (
        <>
          <BookPicker books={books} selected={bookId} onSelect={onSelectBook} uses="The generator and its asset list use" />
          <GroundedGenerator refresh={refresh} bookId={bookId} onChange={onChange} />
        </>
      ) : (
        <CampaignBuilder refresh={refresh} onChange={onChange} />
      )}
    </>
  );
}
