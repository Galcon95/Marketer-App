import type { NextConfig } from "next";

/** Next.js build and runtime configuration. */
const nextConfig: NextConfig = {
  cacheComponents: true, // enable Cache Components (use cache / partial prerendering)
  partialPrefetching: true, // <Link> prefetches only the static parts of routes; requires cacheComponents
};

export default nextConfig;
