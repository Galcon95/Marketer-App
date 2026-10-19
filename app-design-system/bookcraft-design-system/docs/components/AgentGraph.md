LangGraph-style node graph: agent nodes joined by animated connection lines that show live data flow.

**Props:** `nodes` `[{id, name, model, icon, state: idle|running|done|waiting, stat?}]` in pipeline order.

- `running`: `accent` icon tile, `accent-soft` halo, spinning refresh. `done`: emerald check. `waiting` (the human gate): dashed `warning-text` border.
- Edges animate (`accent-text` dashes plus a travelling packet) only into the running node; finished edges idle in emerald; edges to queued nodes are static. Motion stops under `prefers-reduced-motion`.
- The canvas is `surface-sunken` with a 16px dot grid in `border`.
