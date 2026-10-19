Streaming agent terminal: timestamp, agent, message — colour-coded by kind.

**Props:** `lines` `[{t, agent, kind: think|tool|info|pass|fail|gate, msg}]`, `live`, `onToggle` (pause/resume), `title`, `height`.

- Kinds: `think` `ink-muted` reasoning, `tool` `info-text` (`call_tool: …`), `pass` `success-text` (`AUDIT PASS: …`), `fail` `danger-text` (`AUDIT FAIL/WARN: …`), `gate` `warning-text`. The prefix word carries the meaning, not just the colour.
- Auto-scrolls to the newest line; `role="log"` announces politely.
