"use client";
/**
 * BookCraft AI — React + Tailwind primitives (shadcn/ui-style: local source, tokens via Tailwind).
 * Needs: react 18+, lucide-react, clsx, Tailwind with tailwind/preset.v3.js, tokens.css and react/base.css.
 */
import { forwardRef, useEffect, useId, useRef, type ButtonHTMLAttributes, type HTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { ChevronDown, Loader2, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "./utils";

/* ---------- Button ---------- */
type Variant = "primary" | "success" | "danger" | "secondary" | "ghost";
const VARIANT: Record<Variant, string> = {
  primary: "bg-accent text-accent-on hover:bg-accent-hover",
  success: "bg-success text-success-on hover:brightness-110",
  danger: "border border-danger-text text-danger-text hover:bg-danger-soft",
  secondary: "border border-line-strong bg-surface-raised text-ink hover:border-ink-muted",
  ghost: "text-ink-muted hover:bg-surface-raised hover:text-ink",
};
export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> { variant?: Variant; size?: "md" | "sm" | "icon"; icon?: LucideIcon; loading?: boolean }
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button({ variant = "primary", size = "md", icon: Icon, loading, className, children, disabled, ...rest }, ref) {
  return (
    <button ref={ref} type="button" disabled={disabled || loading} {...rest}
      className={cn("inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        size === "md" && "h-9 px-3 text-[13px]", size === "sm" && "h-7 gap-1 px-2 text-xs", size === "icon" && "h-8 w-8",
        VARIANT[variant], className)}>
      {loading ? <Loader2 className="animate-spin" size={size === "md" ? 16 : 14} aria-hidden /> : Icon && <Icon size={size === "md" ? 16 : 14} aria-hidden />}
      {children}
    </button>
  );
});

/* ---------- Badge ---------- */
export type Tone = "neutral" | "accent" | "success" | "warning" | "danger";
const TONE: Record<Tone, string> = {
  neutral: "border border-line bg-surface-raised text-ink-muted",
  accent: "bg-accent-soft text-accent-text",
  success: "bg-success-soft text-success-text",
  warning: "bg-warning-soft text-warning-text",
  danger: "bg-danger-soft text-danger-text",
};
export function Badge({ tone = "neutral", mono, dot, pulse, icon: Icon, className, children, title }: { tone?: Tone; mono?: boolean; dot?: boolean; pulse?: boolean; icon?: LucideIcon; className?: string; children?: ReactNode; title?: string }) {
  return (
    <span title={title} className={cn("inline-flex h-[22px] shrink-0 items-center gap-1.5 whitespace-nowrap px-2", mono ? "rounded-sm font-mono text-[11px]" : "rounded-full text-xs font-medium", TONE[tone], className)}>
      {dot && <Dot pulse={pulse} />}
      {Icon && <Icon size={12} aria-hidden />}
      {children}
    </span>
  );
}
export function Dot({ pulse, className }: { pulse?: boolean; className?: string }) {
  return <i aria-hidden className={cn("relative h-1.5 w-1.5 shrink-0 rounded-full bg-current", className)}>{pulse && <i className="absolute -inset-[3px] animate-ping2 rounded-full border border-current" />}</i>;
}

/* ---------- Card ---------- */
export function Card({ title, icon: Icon, meta, actions, flush, className, bodyClassName, children }: { title?: ReactNode; icon?: LucideIcon; meta?: ReactNode; actions?: ReactNode; flush?: boolean; className?: string; bodyClassName?: string; children?: ReactNode }) {
  return (
    <section className={cn("min-w-0 rounded-lg border border-line bg-surface", className)}>
      {(title || actions) && (
        <header className="flex min-h-12 items-center gap-2 border-b border-line px-4 py-3">
          {Icon && <Icon size={16} className="shrink-0 text-accent-text" aria-hidden />}
          <h3 className="min-w-0 flex-1 truncate text-sm font-semibold">{title}</h3>
          {meta}{actions}
        </header>
      )}
      <div className={cn(!flush && "p-4", bodyClassName)}>{children}</div>
    </section>
  );
}

/* ---------- Form fields ---------- */
export function Field({ label, hint, error, children, className, htmlFor }: { label?: string; hint?: ReactNode; error?: string; children: ReactNode; className?: string; htmlFor?: string }) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1.5", className)}>
      {label && <label htmlFor={htmlFor} className="label">{label}</label>}
      {children}
      {error ? <span className="text-xs text-danger-text" role="alert">{error}</span> : hint && <span className="text-xs text-ink-subtle">{hint}</span>}
    </div>
  );
}
export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...p }, ref) {
  return <input ref={ref} {...p} className={cn("field", className)} />;
});
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...p }, ref) {
  return <textarea ref={ref} {...p} className={cn("field min-h-[84px] resize-y", className)} />;
});
export function Select({ className, children, ...p }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className="relative">
      <select {...p} className={cn("field cursor-pointer appearance-none pr-8", className)}>{children}</select>
      <ChevronDown size={16} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-ink-muted" aria-hidden />
    </div>
  );
}
export function Switch({ checked, onChange, label, description }: { checked: boolean; onChange: (v: boolean) => void; label: string; description?: string }) {
  const id = useId();
  return (
    <div className="flex items-start gap-3">
      <button id={id} role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
        className={cn("relative mt-0.5 h-5 w-9 shrink-0 rounded-full border transition-colors", checked ? "border-transparent bg-accent" : "border-line-strong bg-surface-raised")}>
        <span className={cn("absolute left-0 top-[2px] h-3.5 w-3.5 rounded-full transition-transform", checked ? "translate-x-[18px] bg-accent-on" : "translate-x-[2px] bg-ink-muted")} />
      </button>
      <label htmlFor={id} className="cursor-pointer text-[13px] leading-5">{label}{description && <span className="block text-xs text-ink-subtle">{description}</span>}</label>
    </div>
  );
}
export function Checkbox({ checked, onChange, label, className }: { checked: boolean; onChange: (v: boolean) => void; label: string; className?: string }) {
  return <input type="checkbox" aria-label={label} checked={checked} onChange={(e) => onChange(e.target.checked)} className={cn("h-4 w-4 shrink-0 cursor-pointer rounded-sm accent-[var(--accent)]", className)} />;
}

/* ---------- Tabs / segmented ---------- */
export function Tabs<T extends string>({ items, value, onChange, className }: { items: { id: T; label: ReactNode; count?: number; icon?: LucideIcon }[]; value: T; onChange: (v: T) => void; className?: string }) {
  return (
    <div role="tablist" className={cn("flex gap-1 overflow-x-auto border-b border-line [scrollbar-width:none]", className)}>
      {items.map(({ id, label, count, icon: Icon }) => (
        <button key={id} role="tab" aria-selected={value === id} onClick={() => onChange(id)}
          className={cn("-mb-px flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 pb-2.5 pt-2 text-[13px] font-medium transition-colors",
            value === id ? "border-accent text-ink" : "border-transparent text-ink-muted hover:text-ink")}>
          {Icon && <Icon size={14} aria-hidden className={value === id ? "text-accent-text" : ""} />}{label}
          {count !== undefined && <span className={cn("font-mono text-[11px]", value === id ? "text-accent-text" : "text-ink-subtle")}>{count}</span>}
        </button>
      ))}
    </div>
  );
}

/* ---------- Skeleton / Empty / Progress ---------- */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("animate-shimmer rounded-md bg-surface-raised", className)} />;
}
export function EmptyState({ icon: Icon, title, children, action }: { icon: LucideIcon; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-line-strong px-6 py-10 text-center">
      <span className="grid h-10 w-10 place-items-center rounded-md bg-accent-soft text-accent-text"><Icon size={20} aria-hidden /></span>
      <p className="text-sm font-semibold">{title}</p>
      {children && <p className="max-w-sm text-[13px] text-ink-muted">{children}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
export function Progress({ value, tone = "accent", className, label }: { value: number; tone?: "accent" | "success" | "warning" | "muted"; className?: string; label?: string }) {
  const bar = { accent: "bg-accent", success: "bg-success", warning: "bg-warning-text", muted: "bg-ink-subtle" }[tone];
  return (
    <div role="progressbar" aria-label={label} aria-valuenow={Math.round(value)} aria-valuemin={0} aria-valuemax={100} className={cn("h-1.5 overflow-hidden rounded-full bg-surface-raised", className)}>
      <i className={cn("block h-full rounded-full transition-[width] duration-500", bar)} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

/* ---------- Drawer (right) and Modal ---------- */
function useEscape(open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
}
export function Drawer({ open, onClose, title, icon: Icon, children, footer, width = 440 }: { open: boolean; onClose: () => void; title: ReactNode; icon?: LucideIcon; children: ReactNode; footer?: ReactNode; width?: number }) {
  useEscape(open, onClose);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { if (open) ref.current?.focus(); }, [open]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden />
      <aside ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : "Details"} style={{ width: `min(${width}px, 100vw)` }}
        className="absolute inset-y-0 right-0 flex animate-slidein flex-col border-l border-line bg-surface shadow-pop outline-none">
        <header className="flex items-center gap-2 border-b border-line px-4 py-3">
          {Icon && <Icon size={16} className="text-accent-text" aria-hidden />}
          <h2 className="flex-1 text-[15px] font-semibold">{title}</h2>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close"><X size={16} /></Button>
        </header>
        <div className="flex-1 overflow-y-auto p-4">{children}</div>
        {footer && <footer className="border-t border-line px-4 py-3">{footer}</footer>}
      </aside>
    </div>
  );
}
export function Modal({ open, onClose, title, children, footer }: { open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode }) {
  useEscape(open, onClose);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden />
      <div role="dialog" aria-modal="true" aria-label={title} className="relative w-full max-w-md animate-fadeup rounded-lg border border-line bg-surface shadow-pop">
        <header className="flex items-center border-b border-line px-4 py-3"><h2 className="flex-1 text-[15px] font-semibold">{title}</h2><Button variant="ghost" size="icon" onClick={onClose} aria-label="Close"><X size={16} /></Button></header>
        <div className="p-4">{children}</div>
        {footer && <footer className="flex justify-end gap-2 border-t border-line px-4 py-3">{footer}</footer>}
      </div>
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded-sm border border-line px-1 font-mono text-[10px] text-ink-subtle">{children}</kbd>;
}
export function SectionTitle({ icon: Icon, title, count, actions }: { icon?: LucideIcon; title: string; count?: number | string; actions?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center gap-2">
      {Icon && <Icon size={16} className="text-accent-text" aria-hidden />}
      <h2 className="text-sm font-semibold">{title}</h2>
      {count !== undefined && <span className="font-mono text-[11px] text-ink-subtle">{count}</span>}
      <span className="flex-1" />
      {actions}
    </div>
  );
}
export function Panel({ className, ...p }: HTMLAttributes<HTMLDivElement>) {
  return <div {...p} className={cn("rounded-lg border border-line bg-surface", className)} />;
}
