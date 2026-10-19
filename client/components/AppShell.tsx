"use client";

import { useCallback, useState, type JSX } from "react";
import {
  Bot, Brain, Cpu, Database, FileText, Menu, Network, Server, Settings,
  Sparkles, SunMoon, Target, Terminal, Users, UserCheck,
} from "lucide-react";
import { api, API_URL, PROJECT_ID } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import ContentGenerator from "./phases/ContentGenerator";
import KnowledgeHub from "./phases/KnowledgeHub";
import { Badge, Button, Card, ErrorNote, Placeholder, SectionHeading, Sidebar, StatusRow, Tabs, type NavGroup, type TabItem } from "./ui";

type PhaseId = "p1" | "p2" | "p3" | "p4";
type PhaseProps = { refresh: number; onChange: () => void };

const TABS: TabItem<PhaseId>[] = [
  { id: "p1", kicker: "PHASE 1", label: "Content Generator", icon: Sparkles },
  { id: "p2", kicker: "PHASE 2", label: "Knowledge Hub", icon: Database },
  { id: "p3", kicker: "PHASE 3", label: "Market Intelligence", icon: Network },
  { id: "p4", kicker: "PHASE 4", label: "Agent Workspace", icon: Cpu },
];

const TITLES: Record<PhaseId, [title: string, crumb: string]> = {
  p1: ["Content generator", "Zero-shot prompts · no grounding"],
  p2: ["Knowledge hub", "Retrieval-augmented generation over your content"],
  p3: ["Market intelligence", "Live tool calls via Model Context Protocol"],
  p4: ["Agent workspace", "Strategist → Copywriter → Auditor → You"],
};

const SERVICE_META: Record<string, { label: string; icon: typeof Server }> = {
  api: { label: "API", icon: Server },
  vector_db: { label: "Vector DB", icon: Database },
  llm: { label: "LLM", icon: Brain },
};

/* ---------- Phases without backend endpoints yet (dummies) ---------- */

function MarketIntelligence() {
  return (
    <>
      <div className="bc-grid bc-g3">
        {["mcp-server-1", "mcp-server-2", "mcp-server-3"].map((name) => (
          <Card key={name} title={name} icon={Network} meta={<Badge tone="warning">Not connected</Badge>}>
            <span className="bc-hint">MCP server placeholder</span>
          </Card>
        ))}
      </div>
      <Card title="High-intent leads" icon={Target} meta={<Badge mono>0 rows</Badge>}>
        <Placeholder icon={Target}>Leads table will appear here.</Placeholder>
      </Card>
    </>
  );
}

const AGENTS = [
  { name: "Strategist", icon: Target },
  { name: "Copywriter", icon: Bot },
  { name: "Auditor", icon: Cpu },
  { name: "Human checkpoint", icon: UserCheck },
];

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

const VIEWS: Record<PhaseId, (props: PhaseProps) => JSX.Element> = {
  p1: ContentGenerator,
  p2: KnowledgeHub,
  p3: MarketIntelligence,
  p4: AgentWorkspace,
};

/* ---------- Shell ---------- */

export default function AppShell() {
  const [tab, setTab] = useState<PhaseId>("p1");
  const [navOpen, setNavOpen] = useState(false);
  // Bumped after any change (upload, delete, generate) so every list and count reloads.
  const [refresh, setRefresh] = useState(0);
  const onChange = useCallback(() => setRefresh((n) => n + 1), []);

  const health = useApi(`health:${refresh}`, api.health);
  const project = useApi(`project:${refresh}`, api.getProject);
  const p = project.data;
  const View = VIEWS[tab];

  const nav: NavGroup[] = [
    {
      title: "Pipeline",
      items: TABS.map(({ id, label, icon }) => ({ id, label, icon, count: id === "p2" ? p?.chunk_count : undefined })),
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

  function navigate(id: string) {
    if (id in TITLES) setTab(id as PhaseId);
    setNavOpen(false);
  }

  function toggleTheme() {
    const el = document.documentElement;
    el.dataset.theme = el.dataset.theme === "light" ? "dark" : "light";
  }

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
        project={p?.name ?? PROJECT_ID}
        projectMeta={p ? `${p.source_count} sources · ${p.asset_count} assets` : "loading…"}
        status={status}
      />
      <main className="bc-main">
        <div className="bc-top">
          <Button variant="ghost" size="sm" icon={Menu} className="bc-menu-btn" aria-label="Open navigation" onClick={() => setNavOpen(!navOpen)} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="bc-crumb">{PROJECT_ID} / {TITLES[tab][1]}</div>
            <h1>{TITLES[tab][0]}</h1>
          </div>
          <Badge mono icon={Cpu}>tokens 0 / 200k</Badge>
          <Button variant="secondary" size="sm" icon={FileText} disabled>Export</Button>
        </div>
        <div className="bc-tabs-wrap">
          <Tabs items={TABS} value={tab} onChange={setTab} />
        </div>
        <div className="bc-view" key={tab}>
          {health.error && <ErrorNote>Backend unreachable at {API_URL}. Start it with “uv run fastapi dev server.py” in server/.</ErrorNote>}
          <View refresh={refresh} onChange={onChange} />
        </div>
      </main>
      <Button variant="secondary" size="sm" icon={SunMoon} className="theme-toggle" onClick={toggleTheme}>Theme</Button>
    </div>
  );
}
