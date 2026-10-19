One indexed manuscript chunk with vector metadata: chunk id, chapter id, page, quote score and topic tags.

**Props:** `chunk` `{id, chapter, page, score (0–1), text, tags?}`, `active`, `onClick`.

- Quote score colours: ≥0.85 `success-text`, ≥0.70 `warning-text`, otherwise `ink-muted` — the number is always printed.
- The selected chunk uses `accent-soft` with an `accent-text` border.
