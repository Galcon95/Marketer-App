Status card for one Model Context Protocol server: id, state, headline metric, sparkline and runtime facts.

**Props:** `name` (server id, set in mono), `icon`, `status` Active | Degraded | Offline, `metric`, `metricLabel`, `detail`, `spark` (array of 0–100 bar heights), `footer` (mono facts).

- Server ids are always lowercase kebab-case as deployed (`mcp-reddit-search`).
- Lay three across on desktop, one per row under 1100px.
