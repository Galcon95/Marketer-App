/** BookCraft AI tokens as typed constants (raw values). In UI code prefer the CSS variables: `var(--accent)`. */
export const colors = {
  "dark": {
    "bg": "#09090b",
    "surface": "#18181b",
    "surface-raised": "#27272a",
    "surface-sunken": "#0c0c0e",
    "border": "#27272a",
    "border-strong": "#71717a",
    "ink": "#f4f4f5",
    "ink-muted": "#a1a1aa",
    "ink-subtle": "#8b8b94",
    "accent": "#4f46e5",
    "accent-hover": "#4338ca",
    "on-accent": "#ffffff",
    "accent-text": "#a5b4fc",
    "accent-soft": "#1e1b4b",
    "success": "#10b981",
    "on-success": "#022c22",
    "success-text": "#34d399",
    "success-soft": "#052e22",
    "warning-text": "#fbbf24",
    "warning-soft": "#2a1d05",
    "danger": "#e11d48",
    "danger-text": "#fb7185",
    "danger-soft": "#2c0b14",
    "info-text": "#7dd3fc",
    "chart-1": "#6366f1",
    "chart-2": "#0d9488"
  },
  "light": {
    "bg": "#fafafa",
    "surface": "#ffffff",
    "surface-raised": "#f4f4f5",
    "surface-sunken": "#f4f4f5",
    "border": "#e4e4e7",
    "border-strong": "#8b8b94",
    "ink": "#18181b",
    "ink-muted": "#52525b",
    "ink-subtle": "#6b6b74",
    "accent": "#4f46e5",
    "accent-hover": "#4338ca",
    "on-accent": "#ffffff",
    "accent-text": "#4338ca",
    "accent-soft": "#eef2ff",
    "success": "#047857",
    "on-success": "#ffffff",
    "success-text": "#047857",
    "success-soft": "#ecfdf5",
    "warning-text": "#b45309",
    "warning-soft": "#fffbeb",
    "danger": "#be123c",
    "danger-text": "#be123c",
    "danger-soft": "#fff1f2",
    "info-text": "#0369a1",
    "chart-1": "#4f46e5",
    "chart-2": "#0d9488"
  }
} as const;
export const shadows = {
  "dark": {
    "shadow-pop": "0 8px 24px rgba(0,0,0,0.5)"
  },
  "light": {
    "shadow-pop": "0 8px 24px rgba(24,24,27,0.12)"
  }
} as const;
export const spacing = {
  "space-1": "4px",
  "space-2": "8px",
  "space-3": "12px",
  "space-4": "16px",
  "space-6": "24px",
  "space-8": "32px"
} as const;
export const radius = {
  "radius-sm": "4px",
  "radius-md": "6px",
  "radius-lg": "10px",
  "radius-full": "9999px"
} as const;
export const fonts = {
  "sans": "Geist, \"Inter\", system-ui, -apple-system, \"Segoe UI\", sans-serif",
  "mono": "\"Geist Mono\", \"JetBrains Mono\", ui-monospace, SFMono-Regular, Menlo, monospace"
} as const;
export const typography = {
  "display": {
    "fontSize": "28px",
    "lineHeight": "34px",
    "fontWeight": 600,
    "letterSpacing": "-0.02em",
    "family": "sans"
  },
  "title": {
    "fontSize": "18px",
    "lineHeight": "26px",
    "fontWeight": 600,
    "letterSpacing": "-0.01em",
    "family": "sans"
  },
  "heading": {
    "fontSize": "14px",
    "lineHeight": "20px",
    "fontWeight": 600,
    "family": "sans"
  },
  "body": {
    "fontSize": "14px",
    "lineHeight": "22px",
    "fontWeight": 400,
    "family": "sans"
  },
  "small": {
    "fontSize": "13px",
    "lineHeight": "18px",
    "fontWeight": 400,
    "family": "sans"
  },
  "label": {
    "fontSize": "11px",
    "lineHeight": "16px",
    "fontWeight": 500,
    "letterSpacing": "0.06em",
    "family": "sans"
  },
  "mono": {
    "fontSize": "12px",
    "lineHeight": "18px",
    "fontWeight": 400,
    "family": "mono"
  },
  "mono-tag": {
    "fontSize": "11px",
    "lineHeight": "16px",
    "fontWeight": 500,
    "family": "mono"
  }
} as const;
export type Theme = keyof typeof colors;
export type ColorToken = keyof typeof colors.dark;
