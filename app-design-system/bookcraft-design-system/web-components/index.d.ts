import type { ReactNode, ButtonHTMLAttributes, ChangeEventHandler } from "react";

export type IconName = "check" | "alert" | "cpu" | "database" | "network" | "send" | "refresh" | "copy" | "search" | "upload" | "x" | "book" | "sparkles" | "terminal" | "pencil" | "shield" | "users" | "user" | "layout" | "chevron" | "chevronsUD" | "file" | "message" | "mic" | "star" | "bot" | "target" | "quote" | "menu" | "settings" | "play" | "pause";
export type Tone = "neutral" | "accent" | "success" | "warning" | "danger";

/** Lucide icon, stroke 2, inherits currentColor. */
export interface IconProps { name: IconName; size?: number; label?: string; className?: string; strokeWidth?: number }
/** Command button. */
export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> { variant?: "primary" | "success" | "danger" | "secondary" | "ghost"; size?: "md" | "sm"; icon?: IconName; iconRight?: IconName; loading?: boolean; children?: ReactNode }
/** Status pill or mono metadata tag. */
export interface BadgeProps { tone?: Tone; dot?: boolean; pulse?: boolean; mono?: boolean; icon?: IconName; children?: ReactNode }
/** Bordered surface panel. */
export interface CardProps { title?: ReactNode; icon?: IconName; meta?: ReactNode; actions?: ReactNode; flush?: boolean; children?: ReactNode }
/** Labelled control. */
export interface FieldProps { as?: "text" | "textarea" | "select" | "search"; label?: string; hint?: string; options?: string[]; rows?: number; value?: string; defaultValue?: string; placeholder?: string; onChange?: ChangeEventHandler<any>; id?: string }
/** Phase tabs. */
export interface TabsProps { items: { id: string; label: string; kicker?: string; icon?: IconName }[]; value: string; onChange?: (id: string) => void }
/** App sidebar. */
export interface SidebarProps { project?: string; projectMeta?: string; workspace?: string; nav?: { title: string; items: { id: string; icon: IconName; label: string; count?: number }[] }[]; active?: string; onNavigate?: (id: string) => void; status?: { icon: IconName; label: string; value: string }[] }
/** Generated text asset with copy + word count. */
export interface OutputCardProps { title: string; text: string; icon?: IconName; tag?: string; tagTone?: Tone; limit?: number }
/** Manuscript upload with embedding progress. */
export interface UploadZoneProps { fileName?: string; progress?: number; meta?: string[]; onBrowse?: () => void }
export interface Chunk { id: string; chapter: string; page: number; score: number; text: string; tags?: string[] }
/** Indexed manuscript chunk. */
export interface ChunkCardProps { chunk: Chunk; active?: boolean; onClick?: () => void }
/** Grounded asset with retrieved source citation drawer. */
export interface CitationCardProps { asset: { kind: string; title: string; before: string; quote?: string; after?: string }; citation: { chapter: string; page: number; chunk: string; score: number; text: string; matchChars: number }; defaultOpen?: boolean }
/** MCP server status card. */
export interface McpServerCardProps { name: string; icon?: IconName; status: "Active" | "Degraded" | "Offline"; metric: ReactNode; metricLabel?: string; detail?: ReactNode; spark?: number[]; footer?: string[] }
export interface Lead { id: string | number; kind: "reddit" | "goodreads" | "podcast" | "web"; source: string; question: string; meta?: string; intent: number; keywords: string[]; fresh?: boolean }
/** High-intent leads table. */
export interface LeadsTableProps { rows: Lead[]; onDraft?: (row: Lead) => void }
export interface AgentNode { id: string; name: string; model?: string; icon: IconName; state: "idle" | "running" | "done" | "waiting"; stat?: string }
/** Agent workflow graph with animated edges. */
export interface AgentGraphProps { nodes: AgentNode[] }
export interface LogLine { t: string; agent: string; kind: "think" | "tool" | "info" | "pass" | "fail" | "gate"; msg: string }
/** Streaming agent terminal. */
export interface AgentConsoleProps { lines: LogLine[]; live?: boolean; onToggle?: () => void; title?: string; height?: number }
/** Human-in-the-loop review drawer. */
export interface ReviewPanelProps { draft: string; checks: { ok: boolean; label: string; detail?: string }[]; score?: string; target?: string; title?: string; onApprove?: () => void; onReject?: () => void; onEdit?: () => void }
