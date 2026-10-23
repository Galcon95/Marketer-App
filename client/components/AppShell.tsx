"use client";

/**
 * The app frame: sidebar (navigation, current client, system status from GET /health), top bar (title,
 * usage and costs button, export) and the four phase tabs, which render the phase views. Also holds the
 * Agent Workspace (Phase 4) placeholder.
 */

import { useCallback, useState, useSyncExternalStore, type JSX } from "react";
import {
  Bot, Brain, Cpu, Database, FileText, Menu, Moon, Network, Server, Settings,
  Sparkles, Sun, SunMoon, Target, Terminal, Users, UserCheck,
} from "lucide-react";
import { api, API_URL, PROJECT_ID } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import CampaignBuilder from "./phases/CampaignBuilder";
import KnowledgeHub from "./phases/KnowledgeHub";
import MarketIntelligence from "./phases/MarketIntelligence";
import UsageDrawer, { formatTokens, formatUsd } from "./UsagePanel";
import { Badge, Button, Card, ErrorNote, Placeholder, SectionHeading, Sidebar, StatusRow, Tabs, type NavGroup, type TabItem } from "./ui";

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
/** Props passed to every phase view: `refresh` reloads its data, `onChange` triggers a global refresh. */
type PhaseProps = { refresh: number; onChange: () => void };

/** Tab bar entries, one per phase. */
const TABS: TabItem<PhaseId>[] = [
  { id: "p1", kicker: "PHASE 1", label: "Knowledge Hub", icon: Database },
  { id: "p2", kicker: "PHASE 2", label: "Campaign Builder", icon: Sparkles },
  { id: "p3", kicker: "PHASE 3", label: "Market Intelligence", icon: Network },
  { id: "p4", kicker: "PHASE 4", label: "Agent Workspace", icon: Cpu },
];

/** Page title and breadcrumb subtitle shown in the top bar for each phase. */
const TITLES: Record<PhaseId, [title: string, crumb: string]> = {
  p1: ["Knowledge hub", "Retrieval-augmented generation over your content"],
  p2: ["Campaign builder", "Zero-shot prompts · no grounding"],
  p3: ["Market intelligence", "Live tool calls via Model Context Protocol"],
  p4: ["Agent workspace", "Strategist → Copywriter → Auditor → You"],
};

/** Display label and icon for each service name reported by GET /health. */
const SERVICE_META: Record<string, { label: string; icon: typeof Server }> = {
  api: { label: "API", icon: Server },
  vector_db: { label: "Vector DB", icon: Database },
  llm: { label: "LLM", icon: Brain },
};

/* ---------- Phase without backend endpoints yet (dummy) ---------- */

/** Steps of the planned multi-agent workflow, in order. */
const AGENTS = [
  { name: "Strategist", icon: Target },
  { name: "Copywriter", icon: Bot },
  { name: "Auditor", icon: Cpu },
  { name: "Human checkpoint", icon: UserCheck },
];

/** Phase 4 placeholder: agent cards, console and review area. No API calls yet. */
function AgentWorkspace() {
  return (
    <>
      <div>
        <SectionHeading icon={Network} title="Agent workflow" />
        <div className="bc-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
          {AGENTS.map(({ name, icon }) => (
            <Card key={name} title={name} icon={icon} meta={<Badge mono>idle</Badge>}>
              <span className="bc-hint">Agent placeholder</span>
            </Card>
          ))}
        </div>
      </div>
      <Card title="Agent console" icon={Terminal}>
        <Placeholder icon={Terminal}>Agent logs will stream here.</Placeholder>
      </Card>
      <Card title="Review" icon={UserCheck}>
        <Placeholder icon={UserCheck}>Drafts awaiting your approval will appear here.</Placeholder>
      </Card>
    </>
  );
}

/** Component rendered for each phase tab. */
const VIEWS: Record<PhaseId, (props: PhaseProps) => JSX.Element> = {
  p1: KnowledgeHub,
  p2: CampaignBuilder,
  p3: MarketIntelligence,
  p4: AgentWorkspace,
};

/* ---------- Shell ---------- */

/**
 * The whole app UI: sidebar (navigation, project, system status), top bar, phase tabs and the
 * active phase view. Owns the selected tab, the mobile nav state and the global refresh counter,
 * and loads the health status and the current project (for names and counts).
 */
export default function AppShell() {
  const [tab, setTab] = useState<PhaseId>("p1");
  const [navOpen, setNavOpen] = useState(false); // sidebar visibility on small screens
  // Bumped after any change (upload, delete, generate) so every list and count reloads.
  const [refresh, setRefresh] = useState(0);
  const onChange = useCallback(() => setRefresh((n) => n + 1), []);

  const health = useApi(`health:${refresh}`, api.health);
  const project = useApi(`project:${refresh}`, api.getProject);
  const theme = useTheme();
  // Usage totals for the top bar (reloaded on every change); the panel loads its own data when opened.
  const usage = useApi(`usage:${refresh}`, () => api.usage(1));
  const [usageOpen, setUsageOpen] = useState(0); // > 0 while the usage panel is open; increases per opening
  const closeUsage = useCallback(() => setUsageOpen(0), []);
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
  ];

  /**
   * Handle a sidebar click: switch to the phase if the id is one (library pages do not exist yet)
   * and close the mobile navigation.
   * @param id Id of the clicked link.
   */
  function navigate(id: string) {
    if (id in TITLES) setTab(id as PhaseId);
    setNavOpen(false);
  }

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
      return <StatusRow key={s.name} icon={meta.icon} label={meta.label} value={s.ok ? "Connected" : "Offline"} ok={s.ok} title={s.detail} />;
    });

  return (
    <div className="bc-app bc-root" data-nav={navOpen ? "open" : "closed"}>
      <Sidebar
        nav={nav}
        active={tab}
        onNavigate={navigate}
        client={p?.name ?? PROJECT_ID}
        clientMeta={p ? `${p.source_count} sources · ${p.asset_count} assets` : "loading…"}
        status={status}
      />
      <main className="bc-main">
        <div className="bc-top">
          <Button variant="ghost" size="sm" icon={Menu} className="bc-menu-btn" aria-label="Open navigation" onClick={() => setNavOpen(!navOpen)} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="bc-crumb">{PROJECT_ID} / {TITLES[tab][1]}</div>
            <h1>{TITLES[tab][0]}</h1>
          </div>
          <Button variant="success" size="sm" icon={Cpu} onClick={() => setUsageOpen((n) => n + 1)}
            title={totals ? `All model calls so far: input ${totals.input_tokens.toLocaleString()} tokens (${formatUsd(totals.input_cost)}), output ${totals.output_tokens.toLocaleString()} tokens (${formatUsd(totals.output_cost)}). Click for details.` : "LLM usage and costs"}>
            <span className="bc-mono">{totals ? `${formatUsd(totals.cost)} · ${formatTokens(totals.input_tokens + totals.output_tokens)} tok` : "usage"}</span>
          </Button>
          <Button variant="secondary" size="sm" icon={FileText} disabled>Export</Button>
        </div>
        <div className="bc-tabs-wrap">
          <Tabs items={TABS} value={tab} onChange={setTab} />
        </div>
        {/* key={tab} remounts the view on tab change, resetting its local state. */}
        <div className="bc-view" key={tab}>
          {health.error && <ErrorNote>Backend unreachable at {API_URL}. Start it with “uv run fastapi dev server.py” in server/.</ErrorNote>}
          <View refresh={refresh} onChange={onChange} />
        </div>
      </main>
      {usageOpen > 0 && <UsageDrawer openCount={usageOpen} onClose={closeUsage} />}
      <Button variant="secondary" size="sm" icon={theme === "dark" ? Sun : theme === "light" ? Moon : SunMoon}
        className="theme-toggle" onClick={toggleTheme} aria-label="Switch between light and dark theme">
        {theme === "dark" ? "Light mode" : theme === "light" ? "Dark mode" : "Theme"}
      </Button>
    </div>
  );
}
