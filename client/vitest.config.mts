// Vitest configuration for the client's unit tests (npm test). The tests cover plain TypeScript helpers, so they
// run in Node without a browser environment; see node_modules/next/dist/docs/01-app/02-guides/testing/vitest.md
// for adding React component tests (jsdom + Testing Library) later.
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
  },
});
