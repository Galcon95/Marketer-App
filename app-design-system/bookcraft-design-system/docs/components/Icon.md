Inline Lucide icons drawn from a built-in geometry table, inheriting `currentColor`.

**Props:** `name` (one of `BookCraft.icons`: check, alert, cpu, database, network, send, refresh, copy, search, upload, x, book, sparkles, terminal, pencil, shield, users, user, layout, chevron, chevronsUD, file, message, mic, star, bot, target, quote, menu, settings, play, pause), `size` (px, default 16), `label` (makes it a labelled `img`; otherwise `aria-hidden`).

- Use 16px in controls and lists, 14px in badges and table cells, 20px for upload and empty states.
- Colour comes from the parent: `accent-text` for section icons, `ink-muted` for idle nav, `success-text` / `warning-text` / `danger-text` only next to a word that says the same thing.
- Stroke stays 2. Never fill an icon.
