import AppShell from "@/components/AppShell";

/**
 * Home page ("/"): renders the whole app.
 * All API calls run in the browser (components/AppShell.tsx → lib/api.ts), so the page prerenders statically.
 */
export default function Home() {
  return <AppShell />;
}
