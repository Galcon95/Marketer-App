/**
 * Minimal React UI kit following the design guide in app-design-system/.
 * Markup and class names mirror its bundle so app/styles/bookcraft.css styles them.
 */
import type { ComponentPropsWithRef, ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { AlertTriangle, ChevronDown, ChevronsUpDown, FolderOpen, Megaphone, RefreshCw, Search } from "lucide-react";

export function cx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

/* ---------- Button ---------- */
type ButtonVariant = "primary" | "secondary" | "ghost" | "success" | "danger";
interface ButtonProps extends ComponentPropsWithRef<"button"> {
  variant?: ButtonVariant;
  size?: "md" | "sm";
  icon?: LucideIcon;
  loading?: boolean;
}
export function Button({ variant = "primary", size = "md", icon: Icon, loading, className, children, disabled, ...rest }: ButtonProps) {
  const iconSize = size === "sm" ? 14 : 16;
  return (
    <button
      type="button"
      {...rest}
      disabled={disabled || loading}
      className={cx("bc-btn", `bc-btn-${variant}`, size === "sm" && "bc-btn-sm", className)}
    >
      {loading ? <RefreshCw size={iconSize} className="bc-ico bc-spin" aria-hidden /> : Icon && <Icon size={iconSize} className="bc-ico" aria-hidden />}
      {children}
    </button>
  );
}

/* ---------- Badge ---------- */
type Tone = "neutral" | "accent" | "success" | "warning" | "danger";
export function Badge({ tone = "neutral", mono, dot, pulse, icon: Icon, children }: { tone?: Tone; mono?: boolean; dot?: boolean; pulse?: boolean; icon?: LucideIcon; children?: ReactNode }) {
  return (
    <span className={cx("bc-badge", tone !== "neutral" && `bc-badge-${tone}`, mono && "bc-badge-mono")}>
      {dot && <i className={cx("bc-dot", pulse && "bc-dot-pulse")} />}
      {Icon && <Icon size={12} className="bc-ico" aria-hidden />}
      {children}
    </span>
  );
}

/* ---------- Card ---------- */
export function Card({ title, icon: Icon, meta, actions, flush, className, children }: { title?: string; icon?: LucideIcon; meta?: ReactNode; actions?: ReactNode; flush?: boolean; className?: string; children?: ReactNode }) {
  return (
    <section className={cx("bc-card", className)}>
      {(title || actions) && (
        <header className="bc-card-head">
          {Icon && <Icon size={16} className="bc-ico" aria-hidden />}
          <h3>{title}</h3>
          {meta}
          {actions}
        </header>
      )}
      <div className={flush ? "" : "bc-card-body"}>{children}</div>
    </section>
  );
}

/* ---------- Field ---------- */
interface FieldProps {
  label?: string;
  name?: string;
  as?: "input" | "textarea" | "select" | "search";
  options?: Array<string | { value: string; label: string }>;
  rows?: number;
  placeholder?: string;
  defaultValue?: string;
  required?: boolean;
  hint?: string;
}
export function Field({ label, name, as = "input", options = [], rows = 3, placeholder, defaultValue, required, hint }: FieldProps) {
  const id = `f-${(name ?? label ?? placeholder ?? "field").replace(/\W+/g, "-").toLowerCase()}`;
  const base = { id, name, placeholder, defaultValue, required };
  let control: ReactNode;
  if (as === "textarea") control = <textarea {...base} rows={rows} className="bc-textarea" />;
  else if (as === "select")
    control = (
      <div className="bc-select-wrap">
        <select {...base} className="bc-select">
          {options.map((o) => {
            const { value, label: text } = typeof o === "string" ? { value: o, label: o } : o;
            return <option key={value} value={value}>{text}</option>;
          })}
        </select>
        <ChevronDown size={16} className="bc-ico" aria-hidden />
      </div>
    );
  else if (as === "search")
    control = (
      <div className="bc-search">
        <Search size={16} className="bc-ico" aria-hidden />
        <input {...base} type="search" className="bc-input" aria-label={label ?? placeholder} />
      </div>
    );
  else control = <input {...base} type="text" className="bc-input" />;
  return (
    <div className="bc-field">
      {label && <label className="bc-label" htmlFor={id}>{label}</label>}
      {control}
      {hint && <span className="bc-hint">{hint}</span>}
    </div>
  );
}

/* ---------- Tabs ---------- */
export interface TabItem<T extends string = string> { id: T; kicker?: string; label: string; icon: LucideIcon }
export function Tabs<T extends string>({ items, value, onChange }: { items: TabItem<T>[]; value: T; onChange: (id: T) => void }) {
  return (
    <div className="bc-tabs" role="tablist">
      {items.map(({ id, kicker, label, icon: Icon }) => (
        <button key={id} role="tab" className="bc-tab" aria-selected={value === id} onClick={() => onChange(id)}>
          {kicker && <span className="bc-tab-k">{kicker}</span>}
          <span className="bc-tab-l"><Icon size={14} className="bc-ico" aria-hidden />{label}</span>
        </button>
      ))}
    </div>
  );
}

/* ---------- Sidebar ---------- */
export interface NavGroup { title: string; items: { id: string; icon: LucideIcon; label: string; count?: number }[] }

export function StatusRow({ icon: Icon, label, value, ok, title }: { icon: LucideIcon; label: string; value: string; ok: boolean; title?: string }) {
  return (
    <div className="bc-status-r" title={title}>
      <Icon size={14} className="bc-ico" aria-hidden />
      {label}
      <b style={ok ? undefined : { color: "var(--warning-text)" }}>
        <i className={cx("bc-dot", ok && "bc-dot-pulse")} />
        {value}
      </b>
    </div>
  );
}

export function Sidebar({ nav, active, onNavigate, status, project, projectMeta }: { nav: NavGroup[]; active: string; onNavigate: (id: string) => void; status: ReactNode; project: string; projectMeta: string }) {
  return (
    <aside className="bc-side" aria-label="Main">
      <div className="bc-logo">
        <span className="bc-logo-mark"><Megaphone size={18} className="bc-ico" aria-hidden /></span>
        <div>
          <div className="bc-logo-name">Marketer <span>App</span></div>
          <div className="bc-logo-sub">ai marketing workspace</div>
        </div>
      </div>

      <button className="bc-proj" aria-label="Switch project">
        <span className="bc-proj-ico"><FolderOpen size={14} className="bc-ico" aria-hidden /></span>
        <span style={{ minWidth: 0, flex: 1 }}>
          <span className="bc-label" style={{ display: "block", fontSize: 10, lineHeight: "14px" }}>Current project</span>
          <span className="bc-proj-t" style={{ display: "block" }}>{project}</span>
          <span className="bc-proj-s">{projectMeta}</span>
        </span>
        <ChevronsUpDown size={14} className="bc-ico bc-muted" aria-hidden />
      </button>

      {nav.map((group) => (
        <nav key={group.title} className="bc-nav">
          <div className="bc-nav-h">{group.title}</div>
          {group.items.map(({ id, icon: Icon, label, count }) => (
            <button key={id} className="bc-nav-a" aria-current={active === id ? "page" : undefined} onClick={() => onNavigate(id)}>
              <Icon size={16} className="bc-ico" aria-hidden />
              {label}
              {count != null && <span className="bc-n">{count}</span>}
            </button>
          ))}
        </nav>
      ))}

      <div className="bc-status" role="status">
        <div className="bc-nav-h" style={{ padding: 0 }}>System status</div>
        {status}
      </div>
    </aside>
  );
}

/* ---------- Section heading + placeholder ---------- */
export function SectionHeading({ icon: Icon, title, count, children }: { icon: LucideIcon; title: string; count?: ReactNode; children?: ReactNode }) {
  return (
    <div className="bc-sec-h">
      <Icon size={16} className="bc-ico bc-acc" aria-hidden />
      <h2>{title}</h2>
      {count != null && <span className="bc-n">{count}</span>}
      {children}
    </div>
  );
}

export function Placeholder({ icon: Icon, children }: { icon: LucideIcon; children: ReactNode }) {
  return (
    <div className="bc-empty bc-placeholder">
      <Icon size={20} className="bc-ico" aria-hidden />
      {children}
    </div>
  );
}

/* ---------- Progress, scores, errors ---------- */
export function ProgressBar({ value }: { value: number }) {
  return (
    <div className="bc-bar" data-done={value >= 100} role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
      <i style={{ width: `${value}%` }} />
    </div>
  );
}

/** Shared score scale: ≥0.85 emerald, ≥0.70 amber, below that muted. */
export function Score({ label, value }: { label: string; value: number }) {
  const tier = value >= 0.85 ? "hi" : value >= 0.7 ? "md" : "lo";
  return <span className={`bc-score bc-score-${tier}`}>{label} {value.toFixed(2)}</span>;
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <div className="bc-check" data-ok="false" role="alert">
      <AlertTriangle size={14} className="bc-ico" aria-hidden />
      <span>{children}</span>
    </div>
  );
}
