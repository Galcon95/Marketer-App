Live table of leads scraped by the MCP tools: Source, User question/thread, Detected intent score, Keyword match and a Draft Pitch action.

**Props:** `rows` `[{id, kind: reddit|goodreads|podcast|web, source, question, meta, intent (0–1), keywords[], fresh?}]`, `onDraft(row)`.

- Intent prints as 0–100 with a bar; tiers match ChunkCard (≥85 emerald, ≥70 amber, else muted).
- `fresh` rows flash `accent-soft` once when they stream in. Draft Pitch becomes a “Drafted” secondary button after use.
- Wrap in a `flush` Card; the table scrolls horizontally under 760px.
