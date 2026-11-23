// Starts "next dev" against a chosen FastAPI server, so switching needs no edit of .env.local:
//   npm run dev          → local server (http://127.0.0.1:8000)
//   npm run dev:render   → the server on Render
// The address is passed as NEXT_PUBLIC_API_URL; a variable set in the environment wins over .env.local.
import { spawn } from "node:child_process";

const SERVERS = {
  local: "http://127.0.0.1:8000",
  render: "https://marketer-app.onrender.com",
};

const target = process.argv[2] ?? "local";
const url = SERVERS[target];
if (!url) {
  console.error(`Unknown server "${target}". Use one of: ${Object.keys(SERVERS).join(", ")}`);
  process.exit(1);
}
console.log(`\n  API server: ${url} (${target})\n`);

const child = spawn("next", ["dev", ...process.argv.slice(3)], {
  stdio: "inherit",
  shell: true, // finds next(.cmd) in node_modules/.bin on Windows too
  env: { ...process.env, NEXT_PUBLIC_API_URL: url },
});
child.on("exit", (code) => process.exit(code ?? 0));
