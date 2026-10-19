App sidebar: wordmark, current-book switcher, grouped navigation and the system-status well.

**Props:** `project`, `projectMeta`, `nav` `[{title, items:[{id, icon, label, count?}]}]`, `active`, `onNavigate(id)`, `status` `[{icon, label, value}]` (defaults to MCP Servers 3 Active / Vector DB Connected), `workspace`.

- 256px wide on `surface`; collapses off-canvas under 860px (the shell toggles `data-nav="open"`).
- The status well always shows live infrastructure; values read as `success-text` with a pulsing dot. Use `warning-text` copy for degraded states.
