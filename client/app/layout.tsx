/**
 * Root layout of the Next.js app: fonts, page metadata and the global styles (BookCraft design system).
 */

import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
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

/**
 * Root HTML document wrapping every page. Starts in dark theme (AppShell's toggle changes
 * data-theme at runtime, hence suppressHydrationWarning) and applies the font variables.
 * @param children The page content.
 */
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" data-theme="dark" suppressHydrationWarning className={`${geistSans.variable} ${geistMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
