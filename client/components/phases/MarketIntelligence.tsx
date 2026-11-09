"use client";

/**
 * Phase 3, Market Intelligence: finding where the author's books fit into conversations, in two tabs:
 *   Discussions   the Discussion Relevance Agent: paste a discussion from Reddit, LinkedIn, YouTube or a forum, pick
 *                 a book, and get a recommendation (contribute, more context, skip) with a grounded draft reply
 *                 (DiscussionAgent.tsx)
 *   MCP servers   our MCP servers with their live status and the tool console (McpServers.tsx)
 */

import { useState } from "react";
import { MessagesSquare, Network } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import BookPicker, { readyBooks } from "../BookPicker";
import DiscussionAgent from "../DiscussionAgent";
import { Tabs, type TabItem } from "../ui";
import McpServers from "./McpServers";

/** The two parts of Market Intelligence. */
type IntelTab = "discussions" | "mcp";

const INTEL_TABS: TabItem<IntelTab>[] = [
  { id: "discussions", kicker: "AGENT", label: "Discussions", icon: MessagesSquare },
  { id: "mcp", kicker: "MODEL CONTEXT PROTOCOL", label: "MCP servers", icon: Network },
];

/**
 * Phase 3: Market Intelligence with its two tabs (see the file header).
 * @param refresh Changing it reloads the tab's data.
 * @param onChange Called after an action that changes app data (analyses, usage totals), to refresh the app.
 * @param bookId The book being worked on, shared across the app (null = all books).
 * @param onSelectBook Changes the book being worked on.
 */
export default function MarketIntelligence({ refresh, onChange, bookId: selectedBook, onSelectBook }: {
  refresh: number; onChange: () => void; bookId: string | null; onSelectBook: (id: string | null) => void;
}) {
  const [tab, setTab] = useState<IntelTab>("discussions");
  const sources = useApi(`intel-sources:${refresh}`, api.listSources);
  const books = readyBooks(sources.data ?? []);
  // The shared choice only counts while that book is ready (it may have been deleted or be re-indexing).
  const bookId = selectedBook && books.some((b) => b.id === selectedBook) ? selectedBook : null;

  return (
    <>
      <Tabs items={INTEL_TABS} value={tab} onChange={setTab} />
      {tab === "discussions" ? (
        <>
          <BookPicker books={books} selected={bookId} onSelect={onSelectBook} uses="The agent and its list use" />
          <DiscussionAgent refresh={refresh} books={books} bookId={bookId} onChange={onChange} />
        </>
      ) : (
        <McpServers refresh={refresh} onChange={onChange} />
      )}
    </>
  );
}
