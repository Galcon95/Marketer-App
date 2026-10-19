BookCraft AI is a marketing operating system for authors: it turns a manuscript into grounded pitches, finds readers through live tools, and lets a team of agents draft while a human signs off. The interface is a dark, dense, technical workspace — quiet zinc surfaces, one indigo for action, emerald for “verified and live”.

## Content fundamentals

- **Voice:** precise, calm, a little nerdy. Talk like a senior engineer who also reads a lot of fiction. No hype words (“revolutionary”, “magic”).
- **Person:** address the author as “you”; agents speak in the third person in logs (`strategist`, `auditor`).
- **Casing:** Title Case for buttons and tab labels (“Approve & Dispatch”, “Draft Pitch”); sentence case for headings and body (“High-intent leads”); lowercase kebab-case for machine ids (`mcp-reddit-search`, `chk_0412`).
- **Machine vs human text:** anything a system emits — tool calls, ids, scores, chapter refs, token counts — is set in `mono` / `mono-tag`. Anything a person reads as prose is `body`.
- **Log grammar:** `call_tool: <server> {args}`, `AUDIT PASS: <claim>`, `AUDIT WARN: <claim>`, `GATE: <reason>`. The leading word carries the meaning so colour is never the only signal.
- **No emoji** anywhere in the product UI.

## Visual foundations

- **Theme:** dark is the primary theme (`dark`), light is supported. Page canvas is `bg`; cards, sidebar and panels are `surface`; inputs, hover and active rows are `surface-raised`; consoles, citation drawers and the agent canvas are `surface-sunken`.
- **Text:** `ink` for primary text, `ink-muted` for labels and metadata, `ink-subtle` only for timestamps, counts and placeholders on `surface` or `surface-sunken`. All pairs hold 4.5:1 in both themes.
- **Indigo = action and focus.** `accent` fills the one primary button per region, the active tab underline and the running agent node; text on it is `on-accent`. `accent-text` is for links, section icons and the focus ring; `accent-soft` tints selected rows and highlighted quotes.
- **Emerald = verified and live.** `success` fills only Approve & Dispatch and completion bars (text `on-success`); `success-text` marks Active servers, AUDIT PASS and high scores.
- **Amber = waiting on a human or medium confidence** (`warning-text`, `warning-soft`). **Rose = rejected or failed** (`danger-text`, `danger-soft`). Status colours always travel with an icon or a word, and emerald/rose differ by more than hue alone.
- **Sky** (`info-text`) is reserved for tool calls in logs.
- **Scores:** quote, similarity and intent scores share one scale — ≥0.85 emerald, ≥0.70 amber, below that `ink-muted`.
- **Type:** Geist for UI (`display`, `title`, `heading`, `body`, `small`, `label`), Geist Mono for code and metadata (`mono`, `mono-tag`). Both load from Google Fonts. `label` is uppercase with 0.06em tracking.
- **Spacing:** a 4px base — `space-1` icon gaps, `space-2` inside controls, `space-3` button padding, `space-4` card padding and gutters, `space-6` workspace padding, `space-8` section breaks.
- **Radii:** `radius-sm` tags, `radius-md` controls and nav items, `radius-lg` cards, nodes and drawers, `radius-full` dots and status pills.
- **Borders, not shadows.** Separate surfaces with a 1px `border`; control outlines use `border-strong` (≥3:1). `shadow-pop` is for the review drawer and menus only.
- **Focus:** a solid 2px `accent-text` ring, offset 2px, on every interactive element.
- **Motion:** only to show something live — pulsing status dots, dashed data flowing along agent edges, a travelling packet, a blinking console caret, a one-time flash on newly streamed rows. Everything stops under `prefers-reduced-motion`.
- **Layout:** 256px `Sidebar` + workspace. Grids collapse to one column under 1100px (three-up) and 860px (two-up); the sidebar becomes an off-canvas drawer under 860px; wide tables scroll horizontally inside their card.

## The product pipeline

The four tabs are a progression of capability, always shown in this order with a mono kicker:

1. **Phase 1 — Simple Generator.** Zero-shot prompts. Brief `Card` of `Field`s → `OutputCard`s.
2. **Phase 2 — RAG Knowledge Hub.** `UploadZone`, `ChunkCard` explorer, `CitationCard` with its source drawer.
3. **Phase 3 — MCP Market Intelligence.** `McpServerCard` grid and the `LeadsTable`.
4. **Phase 4 — Autonomous Multi-Agent Workspace.** `AgentGraph`, `AgentConsole`, `ReviewPanel`.

The `Dashboard` page composes all of them; start new screens from it.

## Iconography

- Lucide, stroke 2, round caps, never filled. The geometry is built into the bundle (`BookCraft.Icon`, names in `BookCraft.icons`): check, alert, cpu, database, network, send, refresh, copy, search, upload, x, book, sparkles, terminal, pencil, shield, users, user, layout, chevron, file, message, mic, star, bot, target, quote, menu, settings, play, pause.
- 16px in controls, 14px in badges and tables, 20px in empty and upload states. Icons inherit `currentColor`.
- Meanings are fixed: `check` verified, `alert` needs attention, `cpu` agents/compute, `database` vector store, `network` MCP, `send` dispatch/draft, `refresh` regenerate or running.

## Logo

There is no supplied logo. The sidebar sets the name in type — “BookCraft” in `ink` and “AI” in `accent-text` — beside an `accent` tile holding the Lucide `book` icon. Treat that tile as a placeholder until a real mark exists.

## Using the components

Load React 18, then `components/bundle.css` and `components/bundle.js`; components are on `window.BookCraft`. Every component reads tokens through CSS custom properties, so set `data-theme="dark"` or `"light"` on `<html>`.
