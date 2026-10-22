"use client";

import { useState, type SubmitEvent } from "react";
import { Network, Play, RotateCcw, Target, Terminal, Wrench } from "lucide-react";
import { api, errorMessage, type JsonSchema, type McpCall, type McpServer, type McpTool } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { Badge, Button, Card, ErrorNote, Field, Placeholder, SectionHeading } from "../ui";

/** Props every phase view gets from AppShell: `refresh` reloads data, `onChange` triggers a global refresh. */
type Props = { refresh: number; onChange: () => void };

/* ---------- Tool argument forms (built from the tool's JSON Schema) ---------- */
/** How one argument is entered in the form. */
type ArgKind = "text" | "longtext" | "number" | "boolean" | "select" | "list" | "json";
/** One argument of a tool, ready for the form. */
interface ArgField {
  name: string;
  label: string;
  kind: ArgKind;
  required: boolean;
  options: string[]; // for kind "select"
  defaultValue: string; // the schema's default, as form text
  hint: string;
}
/** Arguments entered as a multi-line text box: free text the user pastes. */
const LONG_TEXT_ARGS = ["text", "question", "brief", "post"];

/**
 * The form fields for a tool's input schema: one per property, in schema order. Optional values
 * (anyOf with null) use their non-null type; enums become selects, numbers number fields, string
 * lists a text box with one item per line, anything else a JSON text box.
 * @param schema The tool's input schema.
 */
function argFields(schema: JsonSchema): ArgField[] {
  const required = new Set(schema.required ?? []);
  return Object.entries(schema.properties ?? {}).map(([name, prop]) => {
    const type = prop.anyOf?.find((s) => s.type !== "null") ?? prop;
    const kind: ArgKind = type.enum ? "select"
      : type.type === "string" ? (LONG_TEXT_ARGS.includes(name) ? "longtext" : "text")
      : type.type === "integer" || type.type === "number" ? "number"
      : type.type === "boolean" ? "boolean"
      : type.type === "array" && type.items?.type === "string" ? "list"
      : "json";
    const hint = [prop.description ?? type.description, kind === "list" ? "One item per line." : "",
      kind === "json" ? "JSON value." : ""].filter(Boolean).join(" ");
    return {
      name, label: prop.title ?? name, kind, required: required.has(name),
      options: kind === "boolean" ? ["true", "false"] : (type.enum ?? []),
      defaultValue: prop.default === undefined || prop.default === null ? "" : String(prop.default), hint,
    };
  });
}

/**
 * Read a tool's arguments from the submitted form. Empty optional fields are left out (the tool's
 * default applies); empty required fields and invalid numbers or JSON are reported.
 * @param fields The tool's form fields.
 * @param form The submitted form data.
 * @returns The arguments, or an error message.
 */
function readArgs(fields: ArgField[], form: FormData): { args: Record<string, unknown> } | { error: string } {
  const args: Record<string, unknown> = {};
  for (const f of fields) {
    const raw = String(form.get(f.name) ?? "");
    if (!raw.trim()) {
      if (f.required && f.kind !== "longtext") return { error: `"${f.label}" is required.` };
      if (f.required) args[f.name] = raw; // let the server validate empty text (e.g. validate_input)
      continue;
    }
    if (f.kind === "number") {
      const n = Number(raw);
      if (Number.isNaN(n)) return { error: `"${f.label}" must be a number.` };
      args[f.name] = n;
    } else if (f.kind === "boolean") args[f.name] = raw === "true";
    else if (f.kind === "list") args[f.name] = raw.split("\n").map((l) => l.trim()).filter(Boolean);
    else if (f.kind === "json") {
      try {
        args[f.name] = JSON.parse(raw);
      } catch {
        return { error: `"${f.label}" is not valid JSON.` };
      }
    } else args[f.name] = raw;
  }
  return { args };
}

/* ---------- Server cards ---------- */
/**
 * Status card of one MCP server (design system McpServerCard): name, status, description, number of
 * tools and its endpoint, audience and latency. Clicking it opens the server in the tool console.
 * @param server The server.
 * @param selected True if it is open in the console.
 * @param onSelect Called on click.
 */
function ServerCard({ server, selected, onSelect }: { server: McpServer; selected: boolean; onSelect: () => void }) {
  const active = server.status === "active";
  return (
    <button type="button" className="bc-mcp" onClick={onSelect} disabled={!active}
      title={active ? "Open in the tool console" : server.error ?? "Offline"}
      style={{ textAlign: "left", font: "inherit", color: "inherit", cursor: active ? "pointer" : "default",
        borderColor: selected ? "var(--accent)" : undefined }}>
      <div className="bc-mcp-h">
        <span className="bc-mcp-ico"><Network size={18} aria-hidden /></span>
        <span className="bc-mcp-n">{server.name}</span>
        <Badge tone={active ? "success" : "danger"} dot>{active ? "Active" : "Offline"}</Badge>
      </div>
      <div className="bc-mcp-d">{active ? server.description : server.error}</div>
      <div className="bc-mcp-m"><b>{server.tools.length}</b><span>tools</span></div>
      <div className="bc-mcp-f">
        <span>{new URL(server.url).pathname}</span>
        <span>{server.audience === "external" ? "external clients" : "app + external"}</span>
        {server.latency_ms !== null && <span>{server.latency_ms} ms</span>}
      </div>
    </button>
  );
}

/* ---------- Tool console ---------- */
/**
 * The result of a tool call: status, duration, and the structured result (or text / error) as JSON.
 * @param call The call to show.
 */
function CallResult({ call }: { call: McpCall }) {
  const body = call.structured !== null && call.structured !== undefined
    ? JSON.stringify(call.structured, null, 2) : call.text || "(empty result)";
  return (
    <div className="bc-stack" style={{ gap: 8 }}>
      <div className="bc-row" style={{ gap: 8 }}>
        <Badge tone={call.ok ? "success" : "danger"} dot>{call.ok ? "ok" : "error"}</Badge>
        <Badge mono>{call.server}/{call.tool}</Badge>
        <Badge mono>{call.duration_ms} ms</Badge>
        <span className="bc-hint">{new Date(call.called_at).toLocaleTimeString()}</span>
      </div>
      <pre className="bc-mono" style={{ margin: 0, padding: 12, maxHeight: 420, overflow: "auto", fontSize: 12,
        whiteSpace: "pre-wrap", wordBreak: "break-word", background: "var(--surface-sunken)",
        border: "1px solid var(--border)", borderRadius: "var(--radius-md)",
        color: call.ok ? undefined : "var(--danger-text)" }}>
        {body}
      </pre>
    </div>
  );
}

/**
 * Form for one tool: its description, one field per argument (from the input schema) and Run.
 * Keyed by server and tool by the parent, so switching tools starts with a fresh form.
 * @param server The tool's server.
 * @param tool The tool.
 * @param onResult Called with the finished call (also failed ones).
 */
function ToolForm({ server, tool, onResult }: { server: McpServer; tool: McpTool; onResult: (call: McpCall) => void }) {
  const fields = argFields(tool.input_schema);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Form submit: read the arguments and call the tool over MCP. */
  async function submit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    const read = readArgs(fields, new FormData(e.currentTarget));
    if ("error" in read) return setError(read.error);
    setPending(true);
    setError(null);
    try {
      onResult(await api.callMcpTool(server.name, tool.name, read.args));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="bc-stack" onSubmit={submit}>
      <div className="bc-row" style={{ gap: 8 }}>
        <Badge mono>{tool.name}</Badge>
        {tool.read_only && <Badge tone="success">read-only</Badge>}
      </div>
      <span className="bc-hint" style={{ whiteSpace: "pre-wrap" }}>{tool.description}</span>
      {fields.length === 0 && <span className="bc-hint">This tool takes no arguments.</span>}
      {fields.map((f) => (
        <Field key={f.name} name={f.name} label={f.required ? `${f.label} *` : f.label} hint={f.hint || undefined}
          as={f.kind === "longtext" || f.kind === "list" || f.kind === "json" ? "textarea"
            : f.kind === "select" || f.kind === "boolean" ? "select" : "input"}
          rows={f.kind === "longtext" ? 4 : 3} options={f.options}
          defaultValue={f.defaultValue} placeholder={f.kind === "number" ? f.defaultValue || "number" : undefined} />
      ))}
      <Button type="submit" icon={Play} loading={pending}>{pending ? "Calling…" : "Run tool"}</Button>
      {error && <ErrorNote>{error}</ErrorNote>}
    </form>
  );
}

/* ---------- Call log ---------- */
/** Short JSON preview of a call's arguments for the log line. */
function argsPreview(args: Record<string, unknown>) {
  const json = JSON.stringify(args);
  return json.length > 90 ? json.slice(0, 87) + "…" : json;
}

/**
 * The console's call log (design system log grammar `call_tool: <server> {args}`), newest first.
 * Clicking a line shows that call's result.
 * @param calls The calls.
 * @param onOpen Called with the clicked call.
 */
function CallLog({ calls, onOpen }: { calls: McpCall[]; onOpen: (call: McpCall) => void }) {
  return (
    <div className="bc-con">
      <div className="bc-con-h"><Terminal size={14} aria-hidden /> call log <Badge mono>{calls.length}</Badge></div>
      <div className="bc-con-b">
        {calls.length === 0 && <div className="bc-log"><span className="bc-log-m bc-hint">No tool calls yet.</span></div>}
        {calls.map((c) => (
          <button key={c.id} type="button" className="bc-log" data-kind={c.ok ? "pass" : "fail"} onClick={() => onOpen(c)}
            title="Show this result"
            style={{ width: "100%", textAlign: "left", background: "none", border: 0, font: "inherit", cursor: "pointer" }}>
            <span className="bc-log-t">{new Date(c.called_at).toLocaleTimeString()}</span>
            <span className="bc-log-a">{c.server.replace(/^mcp-/, "")}</span>
            <span className="bc-log-m">
              call_tool: {c.tool} {argsPreview(c.arguments)} → {c.ok ? "ok" : "error"} · {c.duration_ms} ms
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

/* ---------- Phase 3 ---------- */
/**
 * Phase 3: Market Intelligence. Shows our MCP servers (live status and tools, via GET /mcp-servers) and a
 * tool console like the MCP Inspector: pick a server and tool, fill in the form generated from the tool's
 * input schema, run it over MCP and see the result; every call goes to the call log. The leads table is
 * still a placeholder.
 */
export default function MarketIntelligence({ refresh, onChange }: Props) {
  const servers = useApi(`mcp-servers:${refresh}`, api.listMcpServers);
  const calls = useApi(`mcp-calls:${refresh}`, api.listMcpCalls);
  const [serverName, setServerName] = useState<string | null>(null); // chosen server; null = first active
  const [toolName, setToolName] = useState<string | null>(null); // chosen tool; null = the server's first
  const [shown, setShown] = useState<McpCall | null>(null); // result shown in the console

  const list = servers.data ?? [];
  const active = list.filter((s) => s.status === "active");
  const server = active.find((s) => s.name === serverName) ?? active[0];
  const tool = server?.tools.find((t) => t.name === toolName) ?? server?.tools[0];

  /** A finished call: show it, reload the log and refresh the app (usage totals, e.g. after ask_book). */
  function handleResult(call: McpCall) {
    setShown(call);
    calls.reload();
    onChange();
  }

  return (
    <>
      <div>
        <SectionHeading icon={Network} title="MCP servers" count={list.length}>
          <Button size="sm" variant="ghost" icon={RotateCcw} onClick={servers.reload} loading={servers.loading}>Refresh</Button>
        </SectionHeading>
        {servers.error ? <ErrorNote>{servers.error}</ErrorNote> : (
          <div className="bc-grid bc-g3">
            {list.map((s) => (
              <ServerCard key={s.name} server={s} selected={s.name === server?.name}
                onSelect={() => { setServerName(s.name); setToolName(null); }} />
            ))}
            {!servers.data && <Placeholder icon={Network}>Connecting to the MCP servers…</Placeholder>}
          </div>
        )}
      </div>

      <Card title="Tool console" icon={Wrench} meta={<Badge mono>Streamable HTTP · MCP client</Badge>}>
        {!server ? (
          <Placeholder icon={Wrench}>{servers.loading ? "Loading tools…" : "No MCP server is active."}</Placeholder>
        ) : (
          <div className="bc-grid bc-g2" style={{ alignItems: "start" }}>
            <div className="bc-stack">
              <div className="bc-row" style={{ gap: 12, alignItems: "flex-start" }}>
                <div style={{ flex: 1, minWidth: 160 }}>
                  <Field key={`server-${server.name}`} label="Server" as="select" defaultValue={server.name}
                    options={active.map((s) => s.name)} onChange={(v) => { setServerName(v); setToolName(null); }} />
                </div>
                <div style={{ flex: 1, minWidth: 160 }}>
                  <Field key={`tool-${server.name}`} label="Tool" as="select" defaultValue={tool?.name}
                    options={server.tools.map((t) => t.name)} onChange={setToolName} />
                </div>
              </div>
              {tool && <ToolForm key={`${server.name}/${tool.name}`} server={server} tool={tool} onResult={handleResult} />}
            </div>
            <div className="bc-stack">
              <div className="bc-label">Result</div>
              {shown ? <CallResult call={shown} /> : (
                <Placeholder icon={Play}>Run a tool to see its result here, or click a line in the call log.</Placeholder>
              )}
            </div>
          </div>
        )}
      </Card>

      {calls.error ? <ErrorNote>{calls.error}</ErrorNote> : <CallLog calls={calls.data ?? []} onOpen={setShown} />}

      <Card title="High-intent leads" icon={Target} meta={<Badge mono>0 rows</Badge>}>
        <Placeholder icon={Target}>Leads table will appear here.</Placeholder>
      </Card>
    </>
  );
}
