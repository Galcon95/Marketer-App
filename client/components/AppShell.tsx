"use client";

/**
 * The app frame: sidebar (navigation, current client, system status from GET /health), top bar (title,
 * usage and costs button, MCP keys, export) and the four phase tabs, which render the phase views; the sidebar also
 * opens the MCP servers page (Integrations). Holds the state the
 * views share (refresh counter, the book being worked on) and the Agent Workspace (Phase 4) placeholder.
 * For the public demo's guest account (GET /me `guest`) it shows a banner, hides the Keys button and explains the
 * views the guest cannot use (Agent Workspace, Facebook, YouTube, MCP servers) instead of showing them.
 */

import { useCallback, useEffect, useState, useSyncExternalStore, type JSX } from "react";
import {
  Brain, CircleHelp, Cpu, Database, FileText, Image as ImageIcon, KeyRound, LogOut, MessageCircleQuestion, Menu, MessagesSquare, Moon, Plug, Server, Settings, Sparkles,
  SquarePlay, Sun, SunMoon, ThumbsUp, Users,
} from "lucide-react";
import { api, API_URL } from "@/lib/api";
import { signOut } from "@/lib/supabase";
import { useApi } from "@/lib/useApi";
import ContentStudio from "./phases/ContentStudio";
import KnowledgeHub from "./phases/KnowledgeHub";
import Community from "./phases/Community";
import McpServers from "./phases/McpServers";
import ExportDrawer from "./ExportDrawer";
import FacebookConnection, { type LoginResult } from "./FacebookConnection";
import YouTubeConnection from "./YouTubeConnection";
import AutomationSettings from "./AutomationSettings";
import AskAppDrawer, { type AppChatTurn } from "./AskAppDrawer";
import KeysDrawer from "./KeysPanel";
import LegalFooter from "./LegalFooter";
import UsageDrawer, { formatTokens, formatUsd } from "./UsagePanel";
import { Badge, Button, Card, ErrorNote, Sidebar, StatusRow, Tabs, type NavGroup, type TabItem } from "./ui";

/**
 * Which API server the app talks to, shown next to the breadcrumb in development only (npm run dev = local,
 * npm run dev:render = Render; see scripts/dev.mjs), so a test never goes to the wrong server unnoticed.
 */
const DEV_SERVER = process.env.NODE_ENV === "development"
  ? (/^https?:\/\/(127\.0\.0\.1|localhost)(:|\/|$)/.test(API_URL)
    ? { local: true, label: "local server" }
    : { local: false, label: `server: ${new URL(API_URL).host}` })
  : null;

/** localStorage key of the chosen theme; the theme-init script in app/layout.tsx reads the same key. */
const THEME_KEY = "theme";

/**
 * The current theme from <html data-theme>, kept in sync by watching that attribute (the theme-init script and
 * the Theme button set it). Null while rendering on the server, where the theme is not known yet.
 */
function useTheme(): "light" | "dark" | null {
  return useSyncExternalStore(
    (onChange) => {
      const observer = new MutationObserver(onChange);
      observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
      return () => observer.disconnect();
    },
    () => (document.documentElement.dataset.theme === "light" ? "light" : "dark"),
    () => null,
  );
}

/** Id of one of the four pipeline phases (tabs). */
type PhaseId = "p1" | "p2" | "p3" | "p4";
/** Id of a view: a phase, or a page opened from the sidebar only (no phase tab). */
type ViewId = PhaseId | "mcp" | "facebook" | "youtube";
/**
 * Props passed to every phase view: `refresh` reloads its data, `onChange` triggers a global refresh, `bookId` is
 * the book being worked on (null = all books; shared, so a choice in the Knowledge Hub carries over to the
 * Content Studio) and `onSelectBook` changes it.
 */
type PhaseProps = { refresh: number; onChange: () => void; bookId: string | null; onSelectBook: (id: string | null) => void };

/** Tab bar entries, one per phase. */
const TABS: TabItem<PhaseId>[] = [
  { id: "p1", label: "Knowledge Hub", icon: Database },
  { id: "p2", label: "Content Studio", icon: Sparkles },
  { id: "p3", label: "Community", icon: MessagesSquare },
  { id: "p4", label: "Agent Workspace", icon: Cpu },
];

/** Page title and breadcrumb subtitle shown in the top bar for each view. */
const TITLES: Record<ViewId, [title: string, crumb: string]> = {
  p1: ["Knowledge hub", "Retrieval-augmented generation over your content"],
  p2: ["Content studio", "Grounded assets from your books · zero-shot campaign kits"],
  p3: ["Community", "Discussions worth joining · replies grounded in your books"],
  p4: ["Agent workspace", "The marketing agent · its schedule and cycles · approvals in Telegram"],
  mcp: ["MCP servers", "Integrations · live tool calls via Model Context Protocol"],
  facebook: ["Facebook Page", "Integrations · your own Page, connected with Facebook Login"],
  youtube: ["YouTube channel", "Integrations · your own channel, connected with Google sign-in"],
};

/** What the views the demo's guest cannot use would do, shown to the guest instead of them. */
const GUEST_NOTES: Partial<Record<ViewId, string>> = {
  p4: "The marketing agent works on its own: on a schedule it looks at the author's Facebook Page and YouTube channel, "
    + "drafts replies to readers, questions under videos and new posts about the book (with a picture), and sends each "
    + "one to the author in Telegram. Nothing goes out until the author approves it there.",
  facebook: "Here authors connect their own Facebook Page: read the comments, answer readers with replies drawn from "
    + "their book, and publish posts and ads with pictures.",
  youtube: "Here authors connect their own YouTube channel: read the comments under their videos and answer as the "
    + "channel, with replies drawn from their book.",
  mcp: "The app's books and tools are also available to AI assistants such as Claude Desktop, through MCP servers "
    + "with a personal API key.",
};

/**
 * Shown to the demo's guest instead of a view it cannot use: what the view does, and how to get it.
 * @param note What the view does (GUEST_NOTES).
 */
function GuestNote({ note }: { note: string }) {
  return (
    <Card title="Not available in the demo" icon={Sparkles}>
      <p style={{ margin: 0 }}>{note}</p>
      <p className="bc-hint" style={{ margin: 0 }}>
        It works with your own accounts, so it needs your own sign-up. Log out and choose &ldquo;New here? Create an
        account&rdquo;.
      </p>
    </Card>
  );
}

/** Display label and icon for each service name reported by GET /health. */
const SERVICE_META: Record<string, { label: string; icon: typeof Server }> = {
  api: { label: "API", icon: Server },
  vector_db: { label: "Vector DB", icon: Database },
  llm: { label: "LLM", icon: Brain },
  images: { label: "Pictures", icon: ImageIcon },
};

/** Component rendered for each view. */
const VIEWS: Record<ViewId, (props: PhaseProps) => JSX.Element> = {
  p1: KnowledgeHub,
  p2: ContentStudio,
  p3: Community,
  p4: AutomationSettings,
  mcp: McpServers,
  facebook: () => <></>, // rendered by AppShell itself (it needs the login result)
  youtube: () => <></>, // the same
};

/* ---------- Shell ---------- */

/**
 * The whole app UI: sidebar (navigation, project, system status), top bar, phase tabs and the
 * active phase view. Owns the selected tab, the mobile nav state and the global refresh counter,
 * and loads the health status and the current project (for names and counts).
 */
export default function AppShell() {
  const [tab, setTab] = useState<ViewId>("p1");
  const [navOpen, setNavOpen] = useState(false); // sidebar visibility on small screens
  // Bumped after any change (upload, delete, generate) so every list and count reloads.
  const [refresh, setRefresh] = useState(0);
  const onChange = useCallback(() => setRefresh((n) => n + 1), []);
  // Book being worked on (null = all books), shared by the Knowledge Hub and the Content Studio.
  const [bookId, setBookId] = useState<string | null>(null);

  const health = useApi(`health:${refresh}`, api.health);
  const project = useApi(`project:${refresh}`, api.getProject);
  const theme = useTheme();
  // The signed-in user, their project and whether they are the admin (proxy.ts only lets signed-in users here).
  const me = useApi("me", api.me);
  // The user's usage totals for the top bar (reloaded on every change); the panel loads its own data when opened.
  const usage = useApi(`usage:${refresh}`, () => api.usage(1));
  const [usageOpen, setUsageOpen] = useState(0); // > 0 while the usage panel is open; increases per opening
  const closeUsage = useCallback(() => setUsageOpen(0), []);
  const [keysOpen, setKeysOpen] = useState(false); // the MCP keys panel
  const closeKeys = useCallback(() => setKeysOpen(false), []);
  const [exportOpen, setExportOpen] = useState(false); // the asset export panel
  const closeExport = useCallback(() => setExportOpen(false), []);
  const [askOpen, setAskOpen] = useState(false); // "Ask the app"
  const closeAsk = useCallback(() => setAskOpen(false), []);
  const [askTurns, setAskTurns] = useState<AppChatTurn[]>([]); // its chat, kept while the drawer is closed
  const [login, setLogin] = useState<LoginResult>(null); // result of a Facebook Login that just sent the user back
  const [googleLogin, setGoogleLogin] = useState<LoginResult>(null); // the same for Google sign-in (YouTube)
  const guest = me.data?.guest ?? false; // the public demo's shared guest account
  // The MCP servers run on this server (MCP_SERVERS; off on the public one): otherwise no Keys button, no MCP page.
  const mcpOn = me.data?.mcp ?? true;
  const totals = usage.data?.totals;
  const p = project.data;
  const View = VIEWS[tab];

  // Sidebar links: the four phases (Knowledge Hub shows the chunk count) and library pages.
  const nav: NavGroup[] = [
    {
      title: "Pipeline",
      items: TABS.map(({ id, label, icon }) => ({ id, label, icon, count: id === "p1" ? p?.chunk_count : undefined })),
    },
    {
      title: "Library",
      items: [
        { id: "assets", icon: FileText, label: "Asset Library", count: p?.asset_count },
        { id: "audiences", icon: Users, label: "Audiences" },
        { id: "settings", icon: Settings, label: "Settings" },
      ],
    },
    {
      title: "Integrations",
      items: [
        { id: "facebook", icon: ThumbsUp, label: "Facebook Page" },
        { id: "youtube", icon: SquarePlay, label: "YouTube channel" },
        ...(mcpOn ? [{ id: "mcp", icon: Plug, label: "MCP servers" }] : []),
      ],
    },
  ];

  /**
   * Handle a sidebar click: switch to the phase or page if the id is one (library pages do not exist yet)
   * and close the mobile navigation.
   * @param id Id of the clicked link.
   */
  function navigate(id: string) {
    if (id in TITLES) setTab(id as ViewId);
    setNavOpen(false);
  }

  // Back from Facebook Login (?facebook=...) or Google sign-in (?youtube=...): open that view with the result, and
  // clean the address bar.
  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    const facebook = query.get("facebook");
    const youtube = query.get("youtube");
    if (!facebook && !youtube) return;
    window.history.replaceState(null, "", window.location.pathname);
    const message = query.get("message") ?? "";
    // Deferred: the result comes from the address bar, which only exists in the browser (not during rendering).
    queueMicrotask(() => {
      if (facebook) {
        setLogin({ result: facebook, message });
        setTab("facebook");
      } else if (youtube) {
        setGoogleLogin({ result: youtube, message });
        setTab("youtube");
      }
    });
  }, []);

  /** Switch between light and dark theme via the data-theme attribute on <html>, and remember the choice
   * (the theme-init script in app/layout.tsx applies it on the next visit). */
  function toggleTheme() {
    const next = theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next; // useTheme sees the change and updates the button
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch { /* storage blocked: the theme just isn't remembered */ }
  }

  // Status block: "Unreachable" on error, "Checking…" while loading, else one row per service.
  let status: JSX.Element | JSX.Element[];
  if (health.error) status = <StatusRow icon={Server} label="API" value="Unreachable" ok={false} title={health.error} />;
  else if (!health.data) status = <StatusRow icon={Server} label="API" value="Checking…" ok={false} />;
  else
    status = health.data.services.map((s) => {
      const meta = SERVICE_META[s.name] ?? { label: s.name, icon: Server };
      return <StatusRow key={s.name} icon={meta.icon} label={meta.label} value={s.ok ? "Connected" : s.detail.startsWith("off") ? "Off" : "Offline"} ok={s.ok} title={s.detail} />;
    });

  return (
    <div className="bc-app bc-root" data-nav={navOpen ? "open" : "closed"}>
      <Sidebar
        nav={nav}
        active={tab}
        onNavigate={navigate}
        client={p?.name ?? "…"}
        clientMeta={p ? `${p.source_count} sources · ${p.asset_count} assets` : "loading…"}
        status={status}
      />
      <main className="bc-main">
        <div className="bc-top">
          <Button variant="ghost" size="sm" icon={Menu} className="bc-menu-btn" aria-label="Open navigation" onClick={() => setNavOpen(!navOpen)} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="bc-crumb">
              {TITLES[tab][1]}
              {DEV_SERVER && <> <Badge tone={DEV_SERVER.local ? "success" : "warning"} mono dot>{DEV_SERVER.label}</Badge></>}
            </div>
            <h1>{TITLES[tab][0]}</h1>
          </div>
          <Button variant="success" size="sm" icon={Cpu} onClick={() => setUsageOpen((n) => n + 1)}
            title={totals ? `Your model calls so far: input ${totals.input_tokens.toLocaleString()} tokens (${formatUsd(totals.input_cost)}), output ${totals.output_tokens.toLocaleString()} tokens (${formatUsd(totals.output_cost)}). Click for details.` : "LLM usage and costs"}>
            <span className="bc-mono">{totals ? `${formatUsd(totals.cost)} · ${formatTokens(totals.input_tokens + totals.output_tokens)} tok` : "usage"}</span>
          </Button>
          {!guest && mcpOn && (
            <Button variant="secondary" size="sm" icon={KeyRound} onClick={() => setKeysOpen(true)}
              title="Personal API keys for the MCP servers (Claude Desktop and other tools)">Keys</Button>
          )}
          <Button variant="secondary" size="sm" icon={FileText} onClick={() => setExportOpen(true)}
            title="Download your generated assets as CSV or Markdown">Export</Button>
          <Button variant="secondary" size="sm" icon={MessageCircleQuestion} onClick={() => setAskOpen(true)}
            title="Ask how to do anything in the app: answered from the manual">Ask the app</Button>
          <Button variant="secondary" size="sm" icon={CircleHelp} onClick={() => window.open("/help", "_blank", "noopener")}
            title="The manual: how to do everything in the app (opens in a new tab)">Help</Button>
          <Button variant="ghost" size="sm" icon={LogOut} onClick={signOut} title={me.data ? `Signed in as ${me.data.email}` : undefined}>
            Log out
          </Button>
        </div>
        <div className="bc-tabs-wrap">
          <Tabs items={TABS} value={tab as PhaseId} onChange={setTab} />
        </div>
        {/* key={tab} remounts the view on tab change, resetting its local state. */}
        <div className="bc-view" key={tab}>
          {health.error && <ErrorNote>Backend unreachable at {API_URL}. Start it with “uv run fastapi dev server.py” in server/.</ErrorNote>}
          {guest && (
            <div className="guest-banner" role="status">
              <Badge tone="accent" dot>Guest demo</Badge>
              <p>
                Look around with two classic books: ask them questions, write posts and ads, make pictures. Nothing is
                posted anywhere, and the demo is cleared for the next visitor after 15 quiet minutes.
              </p>
            </div>
          )}
          {guest && GUEST_NOTES[tab]
            ? <GuestNote note={GUEST_NOTES[tab]} />
            : tab === "facebook"
            ? <FacebookConnection key={login?.result ?? "none"} login={login} onChange={onChange} />
            : tab === "youtube"
              ? <YouTubeConnection key={googleLogin?.result ?? "none"} login={googleLogin} onChange={onChange} />
              : <View refresh={refresh} onChange={onChange} bookId={bookId} onSelectBook={setBookId} />}
        </div>
        <LegalFooter />
      </main>
      {usageOpen > 0 && <UsageDrawer openCount={usageOpen} onClose={closeUsage} admin={me.data?.admin} />}
      {keysOpen && <KeysDrawer onClose={closeKeys} />}
      {exportOpen && <ExportDrawer onClose={closeExport} />}
      {askOpen && <AskAppDrawer page={tab} turns={askTurns} setTurns={setAskTurns} onClose={closeAsk} onAnswer={onChange} />}
      <Button variant="secondary" size="sm" icon={theme === "dark" ? Sun : theme === "light" ? Moon : SunMoon}
        className="theme-toggle" onClick={toggleTheme} aria-label="Switch between light and dark theme">
        {theme === "dark" ? "Light mode" : theme === "light" ? "Dark mode" : "Theme"}
      </Button>
    </div>
  );
}
