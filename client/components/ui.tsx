/**
 * Minimal React UI kit following the design guide in app-design-system/.
 * Markup and class names mirror its bundle so app/styles/bookcraft.css styles them.
 */
import { useEffect, useRef, useState, type ComponentPropsWithRef, type ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { AlertTriangle, ChevronDown, Megaphone, RefreshCw, Search, UserRound, X } from "lucide-react";

/**
 * Join CSS class names, skipping falsy values, so classes can be added conditionally.
 * @param parts Class names, or false/null/undefined for classes that should not apply.
 * @returns The space-separated class string, e.g. cx("a", cond && "b") → "a b" or "a".
 */
export function cx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

/* ---------- Button ---------- */
type ButtonVariant = "primary" | "secondary" | "ghost" | "success" | "danger";
/** Props of Button: all native <button> props plus the styling options below. */
interface ButtonProps extends ComponentPropsWithRef<"button"> {
  variant?: ButtonVariant; // color scheme, default "primary"
  size?: "md" | "sm"; // default "md"
  icon?: LucideIcon; // optional icon shown before the label
  loading?: boolean; // shows a spinner instead of the icon and disables the button
}
/**
 * Styled button. Defaults to type="button" so it never submits a form by accident; pass
 * type="submit" explicitly for form buttons. Disabled while `loading`.
 * @param props See ButtonProps; remaining props (onClick, ref, aria-*, ...) go to the <button>.
 */
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
/**
 * Small inline label for statuses, ids and counts.
 * @param tone Color, default "neutral".
 * @param mono Use the monospace font (for ids and numbers).
 * @param dot Show a status dot before the text; `pulse` animates it.
 * @param icon Optional icon before the text.
 * @param children Badge text.
 */
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
/**
 * Bordered content panel with an optional header. The header is rendered only when
 * `title` or `actions` is given.
 * @param title Header title.
 * @param icon Icon before the title.
 * @param meta Content after the title, e.g. a count badge.
 * @param actions Header buttons.
 * @param flush Drop the body padding (for tables that run edge to edge).
 * @param className Extra classes for the outer <section>.
 * @param children Card body.
 */
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
/** Props of Field. Fields are uncontrolled: read their values from the form with FormData via `name`. */
interface FieldProps {
  label?: string; // visible label above the control
  name?: string; // form field name, also used to build the element id
  as?: "input" | "textarea" | "select" | "search"; // which control to render, default "input"
  options?: Array<string | { value: string; label: string }>; // choices for as="select"
  rows?: number; // height of as="textarea", default 3
  placeholder?: string;
  defaultValue?: string;
  required?: boolean;
  hint?: string; // small help text below the control
  onChange?: (value: string) => void; // called with the new value on every change
}
/**
 * Labeled form control: text input, textarea, select box or search input.
 * Derives a stable element id from name/label/placeholder to link the <label> to the control.
 * @param props See FieldProps.
 */
export function Field({ label, name, as = "input", options = [], rows = 3, placeholder, defaultValue, required, hint, onChange }: FieldProps) {
  const id = `f-${(name ?? label ?? placeholder ?? "field").replace(/\W+/g, "-").toLowerCase()}`;
  const handleChange = onChange && ((e: { target: { value: string } }) => onChange(e.target.value));
  const base = { id, name, placeholder, defaultValue, required, onChange: handleChange };
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

/* ---------- Range slider ---------- */
/**
 * Labeled range slider for forms (uncontrolled: read its value with FormData via `name`). Shows the
 * current value and an optional description of it next to the label.
 * @param name Form field name.
 * @param label Visible label.
 * @param min Smallest value.
 * @param max Largest value.
 * @param step Step size.
 * @param defaultValue Initial value.
 * @param describe Optional text for a value, e.g. 80 → "Very human".
 * @param hint Small help text below the slider.
 */
export function RangeField({ name, label, min = 0, max = 100, step = 5, defaultValue, describe, hint }: {
  name: string; label: string; min?: number; max?: number; step?: number; defaultValue: number;
  describe?: (value: number) => string; hint?: string;
}) {
  const [value, setValue] = useState(defaultValue);
  const id = `f-${name}`;
  return (
    <div className="bc-field">
      <label className="bc-label" htmlFor={id} style={{ display: "flex", justifyContent: "space-between" }}>
        <span>{label}</span>
        <span className="bc-mono">{value}{describe ? ` · ${describe(value)}` : ""}</span>
      </label>
      <input id={id} name={name} type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => setValue(Number(e.target.value))} style={{ width: "100%", accentColor: "var(--accent)" }} />
      {hint && <span className="bc-hint">{hint}</span>}
    </div>
  );
}

/* ---------- Tabs ---------- */
/** One tab: `id` is the value reported on click, `kicker` a small line above the label. */
export interface TabItem<T extends string = string> { id: T; kicker?: string; label: string; icon: LucideIcon }
/**
 * Horizontal tab bar (controlled).
 * @param items Tabs to show, in order.
 * @param value Id of the selected tab.
 * @param onChange Called with the id of the clicked tab.
 */
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
/** A titled group of sidebar links; `count` shows a number badge next to a link. */
export interface NavGroup { title: string; items: { id: string; icon: LucideIcon; label: string; count?: number }[] }

/**
 * One line of the sidebar's system status block, e.g. "API ● Connected".
 * @param icon Icon of the service.
 * @param label Service name.
 * @param value Status text.
 * @param ok True shows a pulsing dot; false colors the value as a warning.
 * @param title Tooltip with extra detail.
 */
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

/**
 * Left app sidebar: logo, current client, navigation groups and the system status block.
 * There is one client for now (the API's project "demo-campaign"); switching clients comes with multi-client support.
 * @param nav Navigation groups to render.
 * @param active Id of the active link (marked with aria-current="page").
 * @param onNavigate Called with the id of a clicked link.
 * @param status Content of the status block (usually StatusRow elements).
 * @param client Name of the current client.
 * @param clientMeta Small line under the client name, e.g. counts.
 */
export function Sidebar({ nav, active, onNavigate, status, client, clientMeta }: { nav: NavGroup[]; active: string; onNavigate: (id: string) => void; status: ReactNode; client: string; clientMeta: string }) {
  return (
    <aside className="bc-side" aria-label="Main">
      <div className="bc-logo">
        <span className="bc-logo-mark"><Megaphone size={18} className="bc-ico" aria-hidden /></span>
        <div>
          <div className="bc-logo-name">Marketer <span>App</span></div>
          <div className="bc-logo-sub">ai marketing workspace</div>
        </div>
      </div>

      <div className="bc-proj" style={{ cursor: "default" }}>
        <span className="bc-proj-ico"><UserRound size={14} className="bc-ico" aria-hidden /></span>
        <span style={{ minWidth: 0, flex: 1 }}>
          <span className="bc-label" style={{ display: "block", fontSize: 10, lineHeight: "14px" }}>Current client</span>
          <span className="bc-proj-t" style={{ display: "block" }}>{client}</span>
          <span className="bc-proj-s">{clientMeta}</span>
        </span>
      </div>

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
/**
 * Heading for a page section with an icon and optional count badge.
 * @param icon Icon before the title.
 * @param title Heading text.
 * @param count Number shown in a badge after the title.
 * @param children Extra content at the end of the row, e.g. buttons.
 */
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

/**
 * Dashed empty-state box, used for "nothing here yet", loading text and unbuilt features.
 * @param icon Icon shown above the text.
 * @param children Message.
 */
export function Placeholder({ icon: Icon, children }: { icon: LucideIcon; children: ReactNode }) {
  return (
    <div className="bc-empty bc-placeholder">
      <Icon size={20} className="bc-ico" aria-hidden />
      {children}
    </div>
  );
}

/* ---------- Progress, scores, errors ---------- */
/**
 * Horizontal progress bar; switches to its "done" style at 100.
 * @param value Progress in percent, 0-100.
 */
export function ProgressBar({ value }: { value: number }) {
  return (
    <div className="bc-bar" data-done={value >= 100} role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
      <i style={{ width: `${value}%` }} />
    </div>
  );
}

/**
 * Colored score chip, e.g. "sim 0.94".
 * Shared score scale: ≥0.55 emerald, ≥0.40 amber, below that muted. Tuned for cosine similarity
 * with text-embedding-3-large, where strong matches score about 0.55-0.65 and unrelated text below 0.1.
 * @param label Short prefix such as "sim".
 * @param value Score between 0 and 1, shown with two decimals.
 */
export function Score({ label, value }: { label: string; value: number }) {
  const tier = value >= 0.55 ? "hi" : value >= 0.4 ? "md" : "lo";
  return <span className={`bc-score bc-score-${tier}`}>{label} {value.toFixed(2)}</span>;
}

/**
 * Inline error message with a warning icon; announced to screen readers (role="alert").
 * @param children Error text.
 */
export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <div className="bc-check" data-ok="false" role="alert">
      <AlertTriangle size={14} className="bc-ico" aria-hidden />
      <span>{children}</span>
    </div>
  );
}

/* ---------- Drawer ---------- */
/**
 * Slide-out side panel (dialog): header with icon, title, meta and close button, scrollable body.
 * Focuses the close button on open and closes on Escape or a click on the backdrop.
 * @param icon Icon before the title.
 * @param title Header title.
 * @param label Accessible name of the dialog.
 * @param meta Header content after the title, e.g. a count badge.
 * @param onClose Called to close the drawer; should be stable (useCallback) to avoid re-binding keys.
 * @param children Body content.
 */
export function Drawer({ icon: Icon, title, label, meta, onClose, children }: {
  icon: LucideIcon; title: string; label: string; meta?: ReactNode; onClose: () => void; children: ReactNode;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={label}>
        <header className="drawer-head">
          <Icon size={16} className="bc-ico" aria-hidden />
          <h3>{title}</h3>
          {meta}
          <Button ref={closeRef} variant="ghost" size="sm" icon={X} aria-label="Close" onClick={onClose} />
        </header>
        <div className="drawer-body">{children}</div>
      </aside>
    </>
  );
}
