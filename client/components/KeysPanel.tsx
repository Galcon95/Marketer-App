"use client";

/**
 * The "MCP keys" drawer opened from the top bar: the user's personal API keys for the MCP servers (create, copy,
 * list, revoke). A new key is shown once, with the settings for MCP Inspector and a Claude Desktop config; the server only
 * keeps a hash of it.
 */

import { useState, type FormEvent } from "react";
import { Check, Copy, KeyRound, Trash2 } from "lucide-react";
import { api, API_URL, errorMessage, type ApiKeyCreated, type ApiKeyInfo } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { Badge, Button, Drawer, ErrorNote, Field, Placeholder } from "./ui";

/**
 * Claude Desktop config (claude_desktop_config.json, "mcpServers") for our two MCP servers with this key, via
 * mcp-remote. The key goes into "env" and the header argument has no space ("Authorization:${...}"), because
 * Claude Desktop on Windows splits arguments at spaces.
 * @param key The full API key.
 */
function desktopConfig(key: string) {
  const server = (path: string) => ({
    command: "npx",
    args: ["mcp-remote", `${API_URL}${path}`, "--header", "Authorization:${MARKETER_AUTH}"],
    env: { MARKETER_AUTH: `Bearer ${key}` },
  });
  return JSON.stringify({ "marketer-books": server("/mcp"), "marketer-guardrails": server("/guardrails/mcp") }, null, 2);
}

/**
 * Format an ISO timestamp as a short local date and time.
 * @param iso Timestamp from the API.
 */
function when(iso: string) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/**
 * Button that copies a text to the clipboard and shows "Copied" for two seconds.
 * @param text Text to copy.
 * @param label Button label.
 */
function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setFailed(true);
    }
  }
  return (
    <Button variant="secondary" size="sm" icon={copied ? Check : Copy} onClick={copy}
      title={failed ? "Could not copy: select the text and copy it by hand." : undefined}>
      {copied ? "Copied" : label}
    </Button>
  );
}

/**
 * Side panel with the user's API keys: a form to create one, the new key (once) with its Claude Desktop config,
 * and the list of keys with their first characters, dates and a revoke button.
 * @param onClose Called to close the panel.
 */
export default function KeysDrawer({ onClose }: { onClose: () => void }) {
  const keys = useApi("api-keys", api.listApiKeys);
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Create a key with the name from the form (POST /api-keys) and show it. */
  async function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const name = String(new FormData(form).get("name") ?? "").trim();
    if (!name) return;
    setBusy(true);
    setError(null);
    try {
      setCreated(await api.createApiKey(name));
      form.reset();
      keys.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  /**
   * Revoke a key after confirmation (DELETE /api-keys/{id}).
   * @param key The key to revoke.
   */
  async function revoke(key: ApiKeyInfo) {
    if (!window.confirm(`Revoke the key "${key.name}"? Tools using it stop working at once.`)) return;
    setError(null);
    try {
      await api.revokeApiKey(key.id);
      if (created?.id === key.id) setCreated(null);
      keys.reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Drawer icon={KeyRound} title="MCP keys" label="Personal API keys for the MCP servers" onClose={onClose}
      meta={keys.data ? <Badge mono>{keys.data.length}</Badge> : undefined}>
      <span className="bc-hint">
        Personal keys let tools like Claude Desktop use your books through the MCP servers, as you. Create one key
        per tool, so you can revoke one without breaking the others. Treat a key like a password.
      </span>

      <form className="bc-stack" onSubmit={create}>
        <Field label="New key" name="name" placeholder="What is it for? e.g. Claude Desktop" required />
        <div><Button type="submit" size="sm" icon={KeyRound} loading={busy}>Create key</Button></div>
      </form>
      {error && <ErrorNote>{error}</ErrorNote>}

      {created && (
        <div className="bc-stack" style={{ gap: "var(--space-2)" }}>
          <div className="bc-label">Your new key “{created.name}”</div>
          <span className="bc-hint">Copy it now: it is shown only this once. If you lose it, revoke it and create a new one.</span>
          <code className="bc-mono" style={{ wordBreak: "break-all", userSelect: "all" }}>{created.key}</code>
          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
            <CopyButton text={created.key} label="Copy key" />
            <Button variant="ghost" size="sm" onClick={() => setCreated(null)}>Done</Button>
          </div>

          <div className="bc-label">In MCP Inspector</div>
          <span className="bc-hint">
            Transport type “Streamable HTTP”, this URL (or {API_URL}/guardrails/mcp for the guardrails server), and
            under Authentication the header “Authorization” with the value below; then Connect.
          </span>
          <code className="bc-mono" style={{ wordBreak: "break-all" }}>{API_URL}/mcp</code>
          <code className="bc-mono" style={{ wordBreak: "break-all" }}>Authorization: Bearer {created.key}</code>
          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
            <CopyButton text={`${API_URL}/mcp`} label="Copy URL" />
            <CopyButton text={`Bearer ${created.key}`} label="Copy header value" />
          </div>

          <div className="bc-label">In Claude Desktop</div>
          <span className="bc-hint">
            The config goes into “mcpServers” in claude_desktop_config.json; restart Claude Desktop afterwards.
          </span>
          <div><CopyButton text={desktopConfig(created.key)} label="Copy Claude Desktop config" /></div>
        </div>
      )}

      <div className="bc-label">Your keys</div>
      {keys.error && <ErrorNote>{keys.error}</ErrorNote>}
      {keys.data?.length === 0 && <Placeholder icon={KeyRound}>No keys yet.</Placeholder>}
      {keys.data?.map((k) => (
        <div key={k.id} style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
          <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 2 }}>
            <strong>{k.name}</strong>
            <span className="bc-hint bc-mono">{k.shown}…</span>
            <span className="bc-hint">
              Created {when(k.created_at)} · {k.last_used_at ? `last used ${when(k.last_used_at)}` : "never used"}
            </span>
          </div>
          <Button variant="ghost" size="sm" icon={Trash2} aria-label={`Revoke ${k.name}`} onClick={() => revoke(k)}>
            Revoke
          </Button>
        </div>
      ))}
    </Drawer>
  );
}
