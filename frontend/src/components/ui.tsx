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

export function IntentChip({ intent, muted }: { intent: string; muted?: boolean }) {
  const style = INTENT_STYLES[intent] ?? INTENT_STYLES.other;
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset whitespace-nowrap",
        muted ? "bg-white text-slate-500 ring-slate-200" : style.chip,
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

export function Card({ title, icon, actions, children, className }: {
  title?: ReactNode;
  icon?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cx("rounded-2xl bg-white ring-1 ring-slate-200/80 shadow-[0_1px_2px_rgba(16,24,40,0.04)]", className)}>
      {title && (
        <header className="flex min-h-11 items-center justify-between gap-3 border-b border-slate-100 px-5 py-2">
          <h3 className="flex items-center gap-2 text-sm font-medium text-slate-600 [&_svg]:text-slate-400">
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
