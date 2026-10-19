Command button with an optional leading Lucide icon and a loading state.

**Props:** `variant` — `primary` (indigo `accent` fill, one per view), `success` (emerald, only for Approve & Dispatch / ship actions), `danger` (rose outline, reject/destructive), `secondary` (bordered `surface-raised`), `ghost` (toolbar and inline actions); `size` `md` (36px) | `sm` (28px); `icon`, `iconRight`, `loading`, plus any `<button>` attribute.

- Label with a verb and the object: “Draft Pitch”, “Approve & Dispatch”. Title Case for buttons.
- One `primary` per region. `success` never sits beside another `success`.
- `loading` swaps the icon for a spinning `refresh` and disables the button; change the label to the -ing form.
