/**
 * Root layout of the Next.js app: fonts, page metadata and the global styles (BookCraft design system).
 */

import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Script from "next/script";
import "./globals.css";

// Google fonts, self-hosted by Next.js and exposed as CSS variables for globals.css.
const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

/** Page <title> and meta description. */
export const metadata: Metadata = {
  title: "Marketer App",
  description: "Marketer app frontend",
};

/** localStorage key of the theme the user picked with the Theme button ("light" or "dark"); same as in AppShell. */
const THEME_KEY = "theme";

/**
 * Sets data-theme on <html> before the page is drawn, so there is no flash of the wrong theme: the user's saved
 * choice, else the system setting (light only when the system asks for light; dark is the primary theme).
 */
const THEME_INIT = `try {
  var t = localStorage.getItem("${THEME_KEY}");
  if (t !== "light" && t !== "dark") t = matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  document.documentElement.dataset.theme = t;
} catch (e) {}`;

/**
 * Root HTML document wrapping every page. Starts in dark theme; the THEME_INIT script switches to the saved or
 * system theme before the first paint, and AppShell's toggle changes data-theme at runtime (hence
 * suppressHydrationWarning). Applies the font variables.
 * @param children The page content.
 */
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" data-theme="dark" suppressHydrationWarning className={`${geistSans.variable} ${geistMono.variable}`}>
      <body>
        {children}
        <Script id="theme-init" strategy="beforeInteractive">{THEME_INIT}</Script>
      </body>
    </html>
  );
}
