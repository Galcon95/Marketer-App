import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

/** The origin ("https://host[:port]") of an address, or "" if it is missing or no address. */
function origin(address: string | undefined): string {
  try {
    return address ? new URL(address).origin : "";
  } catch {
    return "";
  }
}

// The only two servers the pages talk to: the FastAPI server (same default as lib/api.ts) and Supabase (sign-in).
const API = origin(process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000");
const SUPABASE = origin(process.env.NEXT_PUBLIC_SUPABASE_URL);

/**
 * Content Security Policy: what the browser may load and where the pages may send data.
 * - script-src: only this site's own scripts. 'unsafe-inline' is needed, because Next.js writes the page data as
 *   inline scripts and Cache Components (partial prerendering) cannot use a per-request nonce; 'unsafe-eval' only
 *   in development (React's error overlay).
 * - connect-src: the API and Supabase, nothing else, so a script that got in cannot send the sign-in token away.
 * - img-src: own pictures, blob: (covers and ad pictures downloaded with the access token), data: (the login
 *   picture's blur preview) and YouTube's video thumbnails.
 * - frame-ancestors 'none': no other site may show the app in a frame (clickjacking).
 */
const CSP = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'", // the components use style attributes
  "img-src 'self' blob: data: https://*.ytimg.com",
  "font-src 'self'", // next/font hosts the fonts on this site
  `connect-src ${["'self'", API, SUPABASE, isDev ? "ws:" : ""].filter(Boolean).join(" ")}`, // ws: hot reload
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

/** Sent with every page and file of the client. */
const SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: CSP },
  { key: "X-Frame-Options", value: "DENY" }, // the same as frame-ancestors, for older browsers
  { key: "X-Content-Type-Options", value: "nosniff" }, // never guess a file's type
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" }, // other sites get the origin, not the path
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" }, // https only (ignored on http)
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
];

/** Next.js build and runtime configuration. */
const nextConfig: NextConfig = {
  cacheComponents: true, // enable Cache Components (use cache / partial prerendering)
  partialPrefetching: true, // <Link> prefetches only the static parts of routes; requires cacheComponents
  headers: async () => [{ source: "/:path*", headers: SECURITY_HEADERS }],
};

export default nextConfig;
