"use client";

/**
 * Phase 3, Community: taking part in conversations where the author's books help. The Discussion Relevance Agent:
 * paste a discussion from Reddit, LinkedIn, YouTube or a forum (or find one with Scan Reddit, or take a comment from
 * the author's Facebook Page), pick a book, and get a recommendation (contribute, more context, skip) with a grounded
 * draft reply (DiscussionAgent.tsx). The MCP servers have their own page (McpServers.tsx, sidebar "Integrations").
 */

import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import BookPicker, { readyBooks } from "../BookPicker";
import DiscussionAgent from "../DiscussionAgent";

/**
 * Phase 3: Community (see the file header).
 * @param refresh Changing it reloads the data.
 * @param onChange Called after an action that changes app data (analyses, usage totals), to refresh the app.
 * @param bookId The book being worked on, shared across the app (null = all books).
 * @param onSelectBook Changes the book being worked on.
 */
export default function Community({ refresh, onChange, bookId: selectedBook, onSelectBook }: {
  refresh: number; onChange: () => void; bookId: string | null; onSelectBook: (id: string | null) => void;
}) {
  const sources = useApi(`community-sources:${refresh}`, api.listSources);
  const books = readyBooks(sources.data ?? []);
  // The shared choice only counts while that book is ready (it may have been deleted or be re-indexing).
  const bookId = selectedBook && books.some((b) => b.id === selectedBook) ? selectedBook : null;

  return (
    <>
      <BookPicker books={books} selected={bookId} onSelect={onSelectBook} uses="The agent and its list use" />
      <DiscussionAgent refresh={refresh} books={books} bookId={bookId} onChange={onChange} />
    </>
  );
}
