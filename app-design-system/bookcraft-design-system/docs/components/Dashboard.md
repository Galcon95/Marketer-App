The complete BookCraft AI workspace: sidebar, phase tabs and the four pipeline views, composed only from the system's components.

It is a page, not a bundle export. Copy its structure when building a screen:

- Shell: `bc-app` → `Sidebar` + `bc-main` (header with crumb and `display`-sized title, `Tabs`, then `bc-view`).
- Phase 1 — `UploadZone`, then `bc-split`: chunk explorer `Card` (search `Field` + `ChunkCard` list) and a stack of `CitationCard`s.
- Phase 2 — `bc-split`: brief `Card` with `Field`s and the primary Generate button; outputs as `OutputCard` grids (3 personas, 5 posts, 1 blurb).
- Phase 3 — three `McpServerCard`s in `bc-g3`, then `LeadsTable` in a flush `Card`.
- Phase 4 — `AgentGraph`, `AgentConsole`, `ReviewPanel`.
- Under 860px the sidebar becomes an off-canvas drawer opened by the menu button.
