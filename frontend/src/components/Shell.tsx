import { useEffect, useState, type ReactNode } from "react";
import { Ban, LayoutGrid, ListChecks, LogOut, Menu, Moon, PenLine, Sun, X } from "lucide-react";
import { useTheme } from "../lib/theme";
import type { GmailStatus, Me } from "../types";
import { Led, cx } from "./ui";

export type Page = "home" | "review";

export function LogoMark({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" className="shrink-0 text-indigo-600" aria-hidden>
      <rect x="0.75" y="0.75" width="30.5" height="30.5" rx="7" fill="currentColor" fillOpacity="0.08" stroke="currentColor" strokeOpacity="0.4" />
      <path d="M8 11.5h16v10.5H8z" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M8 12l8 5.5 8-5.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
  );
}

function Wordmark() {
  return (
    <div className="leading-tight">
      <p className="text-base font-semibold tracking-tight text-slate-950">
        Inbox <span className="text-indigo-600">Helper</span>
      </p>
      <p className="microlabel mt-px !text-[10px] !tracking-[0.22em]">Recruiting triage</p>
    </div>
  );
}

function NavRow({ active, icon, label, badge, onClick }: {
  active: boolean;
  icon: ReactNode;
  label: string;
  badge?: ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className={cx(
        "relative flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[14.5px] font-medium transition-colors",
        active ? "bg-indigo-50 text-indigo-700 ring-1 ring-indigo-200/70 ring-inset" : "text-slate-600 hover:bg-slate-100/70 hover:text-slate-900",
      )}
    >
      {active && <span className="absolute top-1/2 left-0 h-4 w-[2.5px] -translate-y-1/2 rounded-full bg-indigo-500" />}
      {icon}
      <span className="flex-1">{label}</span>
      {badge}
    </button>
  );
}

function GmailLine({ gmail }: { gmail: GmailStatus | null }) {
  if (!gmail?.enabled) return null;
  const [tone, text] = gmail.fetch
    ? (["busy", "Fetching emails…"] as const)
    : !gmail.connected
      ? (["off", "Gmail not connected"] as const)
      : gmail.error
        ? (["warn", "Gmail needs reconnecting"] as const)
        : (["good", "Gmail connected"] as const);
  return (
    <div className="flex items-center gap-2 px-1 text-[12.5px] text-slate-500" title={gmail.account}>
      <Led tone={tone} /> {text}
    </div>
  );
}

function ThemeToggle() {
  const [theme, toggle] = useTheme();
  return (
    <button
      onClick={toggle}
      title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      className="grid size-8 place-items-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-700"
    >
      {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </button>
  );
}

function UserLine({ user, onSignOut }: { user: Me; onSignOut: () => void }) {
  return (
    <div className="flex min-w-0 flex-1 items-center gap-2 px-1" title={`Signed in as ${user.email}. Recorded on every review action.`}>
      <div className="grid size-7 shrink-0 place-items-center rounded-full bg-slate-100 text-xs font-semibold text-slate-600 ring-1 ring-slate-200">
        {(user.name || user.email).slice(0, 1).toUpperCase()}
      </div>
      <div className="min-w-0 flex-1 leading-tight">
        <p className="truncate text-[13px] font-medium text-slate-700">{user.name}</p>
        <p className="truncate text-[11.5px] text-slate-400">{user.mode === "dev" ? "Dev mode · no sign-in" : user.email}</p>
      </div>
      {user.mode === "google" && (
        <button onClick={onSignOut} title="Sign out" aria-label="Sign out" className="grid size-8 place-items-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-700">
          <LogOut className="size-4" />
        </button>
      )}
    </div>
  );
}

type ShellProps = {
  page: Page;
  onPage: (p: Page) => void;
  toReview: number;
  groups?: ReactNode;
  blockedCount: number;
  onBlocklist: () => void;
  onSignature: () => void;
  gmail: GmailStatus | null;
  user: Me | null;
  onSignOut: () => void;
};

/** Everything in the sidebar; the same content opens as a sheet on narrow screens. */
function SidebarBody({ page, onPage, toReview, groups, blockedCount, onBlocklist, onSignature, gmail, user, onSignOut }: ShellProps) {
  return (
    <>
      <div className="flex items-center gap-2.5 px-4 pt-4 pb-5">
        <LogoMark />
        <Wordmark />
      </div>
      <nav aria-label="Main" className="pane flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-3 pb-3">
        <div className="space-y-0.5">
          <p className="microlabel mb-1.5 px-2.5">Workspace</p>
          <NavRow active={page === "home"} icon={<LayoutGrid className="size-4" />} label="Overview" onClick={() => onPage("home")} />
          <NavRow
            active={page === "review"}
            icon={<ListChecks className="size-4" />}
            label="Review queue"
            onClick={() => onPage("review")}
            badge={toReview > 0 && <span className="font-mono text-[11.5px] text-slate-400 tabular-nums">{toReview}</span>}
          />
        </div>
        {page === "review" && groups}
        <div className="space-y-0.5">
          <p className="microlabel mb-1.5 px-2.5">Settings</p>
          <NavRow active={false} icon={<PenLine className="size-4" />} label="Reply signature" onClick={onSignature} />
          <NavRow
            active={false}
            icon={<Ban className="size-4" />}
            label="Blocklist"
            onClick={onBlocklist}
            badge={blockedCount > 0 && <span className="font-mono text-[11.5px] text-slate-400 tabular-nums">{blockedCount}</span>}
          />
        </div>
      </nav>
      <div className="space-y-2.5 border-t border-slate-200/80 px-3 py-3">
        <GmailLine gmail={gmail} />
        <div className="flex items-center gap-1">
          {user ? <UserLine user={user} onSignOut={onSignOut} /> : <span className="flex-1" />}
          <ThemeToggle />
        </div>
      </div>
    </>
  );
}

/** App frame: navigation on the left (groups too while reviewing), the page on the right. */
export function Shell({ children, ...props }: ShellProps & { children: ReactNode }) {
  const [sheet, setSheet] = useState(false);
  useEffect(() => {
    if (!sheet) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setSheet(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sheet]);

  return (
    <div className="flex h-full overflow-hidden">
      <aside className="hidden w-64 shrink-0 flex-col border-r border-slate-200/80 bg-white/70 backdrop-blur-sm lg:flex">
        <SidebarBody {...props} />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* narrow screens: a top bar, and the sidebar as a sheet */}
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-slate-200/80 bg-white/80 px-3 backdrop-blur-sm lg:hidden">
          <button
            onClick={() => setSheet(true)}
            aria-label="Open navigation"
            className="grid size-9 place-items-center rounded-lg text-slate-600 hover:bg-slate-100 hover:text-slate-900"
          >
            <Menu className="size-5" />
          </button>
          <LogoMark size={26} />
          <span className="truncate text-[15px] font-semibold tracking-tight">{props.page === "home" ? "Overview" : "Review queue"}</span>
        </header>
        <main className="min-h-0 flex-1">{children}</main>
      </div>

      {sheet && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="absolute inset-0 bg-slate-900/30 backdrop-blur-sm" onClick={() => setSheet(false)} />
          <div
            className="animate-toast absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col border-r border-slate-200 bg-white shadow-pop"
            // choosing anything in the sheet closes it
            onClick={(e) => (e.target as HTMLElement).closest("nav button") && setSheet(false)}
          >
            <button
              onClick={() => setSheet(false)}
              aria-label="Close navigation"
              className="absolute top-4 right-3 grid size-8 place-items-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700"
            >
              <X className="size-4" />
            </button>
            <SidebarBody {...props} />
          </div>
        </div>
      )}
    </div>
  );
}
