import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { INTENT_STYLES, SEVERITY_STYLES, flagLabel, flagSeverity, intentLabel } from "../lib/labels";
import type { ReviewStatus } from "../types";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "ghost" | "danger" | "destructive" | "success";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-indigo-600 text-white shadow-sm shadow-indigo-600/20 hover:bg-indigo-500 focus-visible:outline-indigo-600",
  success: "bg-emerald-600 text-white shadow-sm shadow-emerald-600/20 hover:bg-emerald-500 focus-visible:outline-emerald-600",
  secondary: "bg-white text-slate-700 ring-1 ring-inset ring-slate-200 hover:bg-slate-50 hover:text-slate-900",
  ghost: "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
  danger: "bg-white text-rose-600 ring-1 ring-inset ring-rose-200 hover:bg-rose-50",
  destructive: "bg-red-600 text-white shadow-sm shadow-red-600/20 hover:bg-red-500 focus-visible:outline-red-600",
};

export function Button({
  variant = "secondary",
  size = "md",
  loading,
  icon,
  children,
  className,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: "sm" | "md";
  loading?: boolean;
  icon?: ReactNode;
}) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors",
        "focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-8 px-2.5 text-[13px]" : "h-9 px-3.5 text-sm",
        VARIANTS[variant],
        className,
      )}
    >
      {loading ? <Loader2 className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

// Only the quarantine groups get a coloured chip; every other intent is told apart by its dot alone.
const LOUD_INTENTS = new Set(["manipulation_attempt", "blocked_sender"]);

export function IntentChip({ intent, muted }: { intent: string; muted?: boolean }) {
  const style = INTENT_STYLES[intent] ?? INTENT_STYLES.other;
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset whitespace-nowrap",
        LOUD_INTENTS.has(intent) && !muted ? style.chip : muted ? "bg-white text-slate-500 ring-slate-200" : "bg-white text-slate-700 ring-slate-200",
      )}
    >
      <span className={cx("size-1.5 rounded-full", style.dot)} />
      {intentLabel(intent)}
    </span>
  );
}

export function FlagChip({ flag, title }: { flag: string; title?: string }) {
  return (
    <span
      title={title}
      className={cx(
        "inline-flex items-center rounded-md px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset whitespace-nowrap",
        SEVERITY_STYLES[flagSeverity(flag)],
      )}
    >
      {flagLabel(flag)}
    </span>
  );
}

const STATUS_STYLES: Record<ReviewStatus, string> = {
  pending: "bg-slate-100 text-slate-600",
  approved: "bg-emerald-50 text-emerald-700",
  rejected: "bg-rose-50 text-rose-700",
  blocked: "bg-zinc-800 text-zinc-50",
};

const STATUS_LABELS: Record<ReviewStatus, string> = {
  pending: "Awaiting review",
  approved: "Approved",
  rejected: "Rejected",
  blocked: "Sender blocked",
};

export function StatusPill({ status }: { status: ReviewStatus }) {
  return (
    <span className={cx("rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap", STATUS_STYLES[status])}>
      {STATUS_LABELS[status]}
    </span>
  );
}

/** Top of a page: a small mono label, the title, and one line on what the page is for. */
export function PageHeader({ eyebrow, title, subtitle, actions }: {
  eyebrow: string;
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        <p className="microlabel !text-indigo-500/80">{eyebrow}</p>
        <h1 className="mt-1 text-[26px] leading-8 font-semibold tracking-tight text-slate-950">{title}</h1>
        {subtitle && <p className="mt-1 max-w-2xl text-sm leading-relaxed text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

/** Small status light: good / busy / warn / crit / off. */
export function Led({ tone, className }: { tone: "good" | "busy" | "warn" | "crit" | "off"; className?: string }) {
  const colour = { good: "bg-emerald-500", busy: "bg-indigo-500 animate-blink", warn: "bg-amber-500", crit: "bg-rose-500", off: "bg-slate-300" }[tone];
  return <span className={cx("led", colour, className)} />;
}

export function Card({ title, icon, actions, children, className }: {
  title?: ReactNode;
  icon?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cx("card", className)}>
      {title && (
        <header className="flex min-h-11 items-center justify-between gap-3 border-b border-slate-100 px-5 py-2">
          <h3 className="microlabel flex items-center gap-2 [&_svg]:text-slate-400">
            {icon}
            {title}
          </h3>
          {actions}
        </header>
      )}
      <div className="px-5 py-4">{children}</div>
    </section>
  );
}
