import AppShell from "@/components/AppShell";

// All API calls run in the browser (components/AppShell.tsx → lib/api.ts), so the page prerenders statically.
export default function Home() {
  return <AppShell />;
}
