/**
 * Tailwind CSS v3 preset for the BookCraft AI design system.
 *   // tailwind.config.js
 *   module.exports = { presets: [require("./bookcraft/tailwind/preset.v3.js")], content: [...] };
 * Load tokens/tokens.css globally. Every colour is a CSS variable, so the
 * data-theme attribute ("dark" | "light") switches themes with no rebuild.
 * Class names: bg-surface, bg-surface-raised, text-ink-muted, border-line-strong,
 * bg-accent, text-accent-text, bg-success-soft, text-danger-text, rounded-lg, shadow-pop …
 */
const v = (name) => `var(--${name})`;
module.exports = {
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        bg: v("bg"),
        surface: { DEFAULT: v("surface"), raised: v("surface-raised"), sunken: v("surface-sunken") },
        line: { DEFAULT: v("border"), strong: v("border-strong") },
        ink: { DEFAULT: v("ink"), muted: v("ink-muted"), subtle: v("ink-subtle") },
        accent: { DEFAULT: v("accent"), hover: v("accent-hover"), on: v("on-accent"), text: v("accent-text"), soft: v("accent-soft") },
        success: { DEFAULT: v("success"), on: v("on-success"), text: v("success-text"), soft: v("success-soft") },
        warning: { text: v("warning-text"), soft: v("warning-soft") },
        danger: { DEFAULT: v("danger"), text: v("danger-text"), soft: v("danger-soft") },
        info: { text: v("info-text") },
        chart: { 1: v("chart-1"), 2: v("chart-2") },
      },
      fontFamily: { sans: [v("font-sans")], mono: [v("font-mono")] },
      borderRadius: { sm: v("radius-sm"), md: v("radius-md"), lg: v("radius-lg") },
      boxShadow: { pop: v("shadow-pop") },
      fontSize: {
        display: ["28px", { lineHeight: "34px", letterSpacing: "-0.02em", fontWeight: "600" }],
        title: ["18px", { lineHeight: "26px", letterSpacing: "-0.01em", fontWeight: "600" }],
        label: ["11px", { lineHeight: "16px", letterSpacing: "0.06em", fontWeight: "500" }],
        tag: ["11px", { lineHeight: "16px", fontWeight: "500" }],
      },
      keyframes: {
        ping2: { from: { transform: "scale(.6)", opacity: ".9" }, to: { transform: "scale(1.8)", opacity: "0" } },
        shimmer: { "0%": { opacity: ".5" }, "50%": { opacity: "1" }, "100%": { opacity: ".5" } },
        slidein: { from: { transform: "translateX(100%)" }, to: { transform: "none" } },
        fadeup: { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "none" } },
        blink: { "50%": { opacity: "0" } },
      },
      animation: {
        ping2: "ping2 1.6s ease-out infinite",
        shimmer: "shimmer 1.4s ease-in-out infinite",
        slidein: "slidein .2s ease-out",
        fadeup: "fadeup .2s ease-out",
        blink: "blink 1s steps(1) infinite",
      },
    },
  },
};
