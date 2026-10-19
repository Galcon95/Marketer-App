Manuscript drop zone with a vector-embedding progress bar.

**Props:** `fileName`, `progress` (0–100; 100 = indexed), `meta` (array of mono facts: size, chapters, chunk count, model), `onBrowse`.

- Accepts .pdf, .epub and .md; say so on the button.
- The bar is `accent` while embedding and turns `success` with an “Indexed” badge when complete.
