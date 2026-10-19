Small status pill or monospace metadata tag.

**Props:** `tone` neutral | accent | success | warning | danger; `dot` (status dot), `pulse` (animated ring — live states only), `icon`, `mono` (square-cornered `mono-tag` for ids, chapters, scores, keywords).

- Status badges always carry a word (“Active”, “Awaiting review”); colour is never the only signal.
- `pulse` means something is streaming or running right now. Remove it when the state settles.
- Use `mono` for machine values (`ch_04`, `chk_0412`, `p.112`); sans for human states.
