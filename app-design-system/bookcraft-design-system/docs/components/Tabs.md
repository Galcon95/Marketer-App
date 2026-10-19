The phase switcher: a row of tabs with a mono kicker (“PHASE 2”) above the label.

**Props:** `items` `[{id, label, kicker?, icon?}]`, `value`, `onChange(id)`.

- The four tabs are the product's complexity pipeline, always in order Phase 1 → 4.
- The active tab gets a 2px `accent` underline and an `accent-text` kicker. Scrolls horizontally on narrow screens.
