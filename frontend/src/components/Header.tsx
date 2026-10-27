import { ChevronDown, Download, LogOut, Plus, ShieldCheck, UserRound } from "lucide-react";
import { api } from "../api";
import { formatWhen } from "../lib/labels";
import type { Me, Run } from "../types";
import { Button } from "./ui";

export function Header({ runs, runId, onSelectRun, user, onSignOut, onNewRun }: {
  runs: Run[];
  runId: number | null;
  onSelectRun: (id: number) => void;
  user: Me | null;
  onSignOut: () => void;
  onNewRun: () => void;
}) {
  return (
    <header className="sticky top-0 z-20 border-b border-slate-200/80 bg-white/85 backdrop-blur">
      <div className="flex h-16 items-center gap-3 px-4 lg:px-6">
        <div className="flex items-center gap-3">
          <div className="grid size-9 place-items-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-md shadow-indigo-500/25">
            <ShieldCheck className="size-5" strokeWidth={2.2} />
          </div>
          <div className="leading-tight">
            <div className="text-[15px] font-semibold tracking-tight whitespace-nowrap">Inbox Helper</div>
            <div className="hidden text-xs text-slate-500 sm:block">AI drafts · people decide · nothing is sent automatically</div>
          </div>
        </div>

        <div className="ml-auto flex min-w-0 items-center gap-2">
          {runs.length > 0 && (
            <label className="relative hidden md:block">
              <span className="sr-only">Inbox run</span>
              <select
                value={runId ?? ""}
                onChange={(e) => onSelectRun(Number(e.target.value))}
                className="h-9 appearance-none rounded-lg bg-white pr-8 pl-3 text-sm text-slate-700 ring-1 ring-slate-200 ring-inset hover:bg-slate-50 focus:ring-2 focus:ring-indigo-500 focus:outline-none"
              >
                {runs.map((r) => (
                  <option key={r.id} value={r.id}>
                    #{r.id} · {r.input_name} · {formatWhen(r.created_at)}
                  </option>
                ))}
              </select>
              <ChevronDown className="pointer-events-none absolute top-2.5 right-2.5 size-4 text-slate-400" />
            </label>
          )}

          {runId && (
            <a href={api.exportUrl(runId)} title="Download approved replies as CSV" className="hidden lg:block">
              <Button variant="ghost" icon={<Download className="size-4" />}>
                Export approved
              </Button>
            </a>
          )}

          {user && (
            <div
              className="flex h-9 items-center gap-2 rounded-lg pr-1 pl-2.5 ring-1 ring-slate-200 ring-inset"
              title={`Signed in as ${user.email}. Recorded on every review action.`}
            >
              <UserRound className="size-4 text-slate-400" />
              <span className="max-w-24 truncate text-sm text-slate-700 sm:max-w-40">{user.name}</span>
              {user.mode === "google" ? (
                <button onClick={onSignOut} title="Sign out" className="grid size-7 place-items-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-700">
                  <LogOut className="size-4" />
                </button>
              ) : (
                <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800" title="AUTH_MODE=dev: no sign-in">DEV</span>
              )}
            </div>
          )}

          <Button variant="primary" icon={<Plus className="size-4" />} onClick={onNewRun}>
            <span className="hidden sm:inline">New triage</span>
          </Button>
        </div>
      </div>
    </header>
  );
}
