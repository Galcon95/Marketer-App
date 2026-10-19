# BookCraft AI Design System

A dark-first, technical UI system: quiet zinc surfaces, **indigo** for action and focus, **emerald** for "verified and live", Geist for UI text and Geist Mono for machine text. Light theme included. Every text/background pair meets WCAG 4.5:1 in both themes.

Open **`preview.html`** in a browser to see every component in a full working layout (needs internet for React and fonts).

## What's in the package

```
tokens/
  tokens.json        source of truth (BookCraft format: themes, usage note on every token)
  tokens.css         CSS custom properties for dark + light, type-style classes
  fonts.css          Google Fonts import for Geist + Geist Mono (load first, or self-host)
  tokens.dtcg.json   W3C Design Tokens format (Style Dictionary, Tokens Studio, Figma variable importers)
  tokens.ts          typed constants for JS/TS (charts, canvas, emails)
tailwind/
  preset.v3.js       Tailwind v3 preset (colours point at CSS variables)
  theme.v4.css       Tailwind v4 @theme block
react/
  primitives.tsx     Button, Badge, Dot, Card, Field, Input, Textarea, Select, Switch, Checkbox,
                     Tabs, Skeleton, EmptyState, Progress, Drawer, Modal, Kbd, SectionTitle, Panel
  base.css           base layer + .label / .field / .mono-tag / .dot-grid helpers
  utils.ts           cn() helper
web-components/
  bundle.js          ready-made React components on window.BookCraft (no build step)
  bundle.css         their styles (bc-* classes)
  index.d.ts         prop types for the bundle
docs/
  brand-book.md      voice, colour roles, type, spacing, motion, iconography rules
  components/*.md    usage guidelines per component
preview.html         live gallery of the whole system
```

## Use it

### Any stack: CSS variables only

```html
<html data-theme="dark">   <!-- or "light" -->
<link rel="stylesheet" href="bookcraft/tokens/fonts.css">
<link rel="stylesheet" href="bookcraft/tokens/tokens.css">
```

```css
.panel { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: var(--space-4); }
.panel h2 { color: var(--ink); font-family: var(--font-sans); }
.panel .meta { color: var(--ink-muted); font-family: var(--font-mono); }
```

Type styles are ready-made classes: `.text-display`, `.text-title`, `.text-heading`, `.text-body`, `.text-small`, `.text-label`, `.text-mono`, `.text-mono-tag`.

### React + Tailwind v3 (Next.js, Vite)

```bash
npm i clsx lucide-react
```

```js
// tailwind.config.js
module.exports = {
  presets: [require("./bookcraft/tailwind/preset.v3.js")],
  content: ["./src/**/*.{ts,tsx}", "./bookcraft/react/**/*.tsx"],
};
```

```css
/* globals.css */
@import "./bookcraft/tokens/fonts.css";
@import "./bookcraft/tokens/tokens.css";
@tailwind base;
@tailwind components;
@tailwind utilities;
@import "./bookcraft/react/base.css";
```

```tsx
import { Button, Badge, Card } from "@/bookcraft/react/primitives";
import { Send } from "lucide-react";

<Card title="Review" actions={<Badge tone="warning" dot pulse>Awaiting review</Badge>}>
  <Button variant="success" icon={Send}>Approve & Dispatch</Button>
</Card>
```

Utility names: `bg-bg`, `bg-surface`, `bg-surface-raised`, `bg-surface-sunken`, `border-line`, `border-line-strong`, `text-ink`, `text-ink-muted`, `text-ink-subtle`, `bg-accent`, `text-accent-on`, `text-accent-text`, `bg-accent-soft`, `bg-success`, `text-success-text`, `bg-success-soft`, `text-warning-text`, `bg-warning-soft`, `text-danger-text`, `bg-danger-soft`, `text-info-text`, `bg-chart-1`, `bg-chart-2`, `rounded-sm|md|lg`, `shadow-pop`, `text-label`, `text-display`, `text-title`.

### Tailwind v4

```css
@import "./bookcraft/tokens/fonts.css";
@import "tailwindcss";
@import "./bookcraft/tokens/tokens.css";
@import "./bookcraft/tailwind/theme.v4.css";
```

This gives you `bg-surface`, `text-ink-muted`, `bg-accent`, `text-accent-text`, `rounded-lg` and so on. Note the names differ slightly from the v3 preset: v4 uses the raw token names (`border-border-strong`, `text-on-accent`). The `react/primitives.tsx` file is written for the v3 preset names.

### No build step: the component bundle

```html
<link rel="stylesheet" href="bookcraft/tokens/tokens.css">
<link rel="stylesheet" href="bookcraft/web-components/bundle.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/react/18.3.1/umd/react.production.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.3.1/umd/react-dom.production.min.js"></script>
<script src="bookcraft/web-components/bundle.js"></script>
<script>
  const { Button, Badge, AgentConsole } = window.BookCraft;
  // ReactDOM.createRoot(el).render(React.createElement(Button, { icon: "send" }, "Dispatch"));
</script>
```

Bundle components: Icon, Button, Badge, Card, Field, Tabs, Sidebar, OutputCard, UploadZone, ChunkCard, CitationCard, McpServerCard, LeadsTable, AgentGraph, AgentConsole, ReviewPanel. Props are in `web-components/index.d.ts` and guidelines are in `docs/components/`.

## Rules worth keeping

- **One indigo action per region.** `accent` fills the primary button; `accent-text` is for links, icons and the focus ring.
- **Emerald means verified or live**, never decoration. Status always comes with an icon or a word, never colour alone.
- **Borders, not shadows.** `shadow-pop` is for drawers, menus and modals only.
- **Machine text is mono:** ids, scores, tool calls, timestamps, token counts.
- **Charts:** use `chart-1` and `chart-2`, which are checked to stay distinguishable for colour-blind readers in both themes. Don't reuse status colours as series colours.
- **Focus:** a solid 2px `accent-text` ring on every interactive element.
- **Motion** only signals something live, and is turned off under `prefers-reduced-motion`.

See `docs/brand-book.md` for the full guide.

## Notes

- Fonts are hosted on Google Fonts (Geist, Geist Mono, OFL licence). For offline or private builds, self-host them, skip `tokens/fonts.css`, and remove the `@import` line at the top of `web-components/bundle.css`.
- The icons are Lucide (ISC licence). They come from `lucide-react` in React, or are built into `bundle.js`.
- There's no logo. The sidebar uses the name set in type plus a placeholder tile with a book icon.
- To change a value, edit `tokens/tokens.json` and update the other token files to match. The four token files carry the same values.
