import type { ReactNode } from "react";
import { Ban, LayoutGrid, ListChecks, LogOut } from "lucide-react";
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

function NavRow({ active, disabled, icon, label, badge, onClick }: {
  active: boolean;
  disabled?: boolean;
  icon: ReactNode;
  label: string;
  badge?: ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cx(
        "relative flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[14.5px] font-medium transition-colors disabled:pointer-events-none disabled:opacity-40",
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

/** App frame: navigation on the left (groups too while reviewing), the page on the right. */
export function Shell({ page, onPage, canReview, toReview, groups, blockedCount, onBlocklist, gmail, user, onSignOut, children }: {
  page: Page;
  onPage: (p: Page) => void;
  canReview: boolean;
  toReview: number;
  groups?: ReactNode;
  blockedCount: number;
  onBlocklist: () => void;
  gmail: GmailStatus | null;
  user: Me | null;
  onSignOut: () => void;
  children: ReactNode;
}) {
  const nav = (
    <>
      <NavRow active={page === "home"} icon={<LayoutGrid className="size-4" />} label="Overview" onClick={() => onPage("home")} />
      <NavRow
        active={page === "review"}
        disabled={!canReview}
        icon={<ListChecks className="size-4" />}
        label="Review queue"
        onClick={() => onPage("review")}
        badge={toReview > 0 && <span className="font-mono text-[11.5px] text-slate-400 tabular-nums">{toReview}</span>}
      />
    </>
  );

  return (
    <div className="flex h-full overflow-hidden">
      <aside className="hidden w-64 shrink-0 flex-col border-r border-slate-200/80 bg-white/70 backdrop-blur-sm lg:flex">
        <div className="flex items-center gap-2.5 px-4 pt-4 pb-5">
          <LogoMark />
          <Wordmark />
        </div>
        <nav className="pane flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-3 pb-3">
          <div className="space-y-0.5">
            <p className="microlabel mb-1.5 px-2.5">Workspace</p>
            {nav}
          </div>
          {page === "review" && groups}
          <div className="space-y-0.5">
            <p className="microlabel mb-1.5 px-2.5">Safety</p>
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
          {user && <UserLine user={user} onSignOut={onSignOut} />}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* narrow screens: a top bar instead of the sidebar */}
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-slate-200/80 bg-white/80 px-3 backdrop-blur-sm lg:hidden">
          <LogoMark size={26} />
          <div className="ml-2 flex gap-1 [&>button]:w-auto">{nav}</div>
          {user?.mode === "google" && (
            <button onClick={onSignOut} title="Sign out" className="ml-auto grid size-9 place-items-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700">
              <LogOut className="size-4" />
            </button>
          )}
        </header>
        <main className="min-h-0 flex-1">{children}</main>
      </div>
    </div>
  );
}

function UserLine({ user, onSignOut }: { user: Me; onSignOut: () => void }) {
  return (
    <div className="flex items-center gap-2 px-1" title={`Signed in as ${user.email}. Recorded on every review action.`}>
      <div className="grid size-7 shrink-0 place-items-center rounded-full bg-slate-100 text-xs font-semibold text-slate-600 ring-1 ring-slate-200">
        {(user.name || user.email).slice(0, 1).toUpperCase()}
      </div>
      <div className="min-w-0 flex-1 leading-tight">
        <p className="truncate text-[13px] font-medium text-slate-700">{user.name}</p>
        <p className="truncate text-[11.5px] text-slate-400">{user.mode === "dev" ? "Dev mode · no sign-in" : user.email}</p>
      </div>
      {user.mode === "google" && (
        <button onClick={onSignOut} title="Sign out" className="grid size-8 place-items-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-700">
          <LogOut className="size-4" />
        </button>
      )}
    </div>
  );
}
