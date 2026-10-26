import { ChevronDown, Download, Plus, ShieldCheck, UserRound } from "lucide-react";
import { api } from "../api";
import { formatWhen } from "../lib/labels";
import type { Run } from "../types";
import { Button } from "./ui";

export function Header({ runs, runId, onSelectRun, reviewer, onReviewer, onNewRun }: {
  runs: Run[];
  runId: number | null;
  onSelectRun: (id: number) => void;
  reviewer: string;
  onReviewer: (name: string) => void;
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

          <label
            className={
              "flex h-9 items-center gap-2 rounded-lg px-2.5 ring-1 ring-inset " +
              (reviewer ? "ring-slate-200" : "bg-amber-50 ring-amber-300")
            }
            title="Your name is recorded on every review action"
          >
            <UserRound className={"size-4 " + (reviewer ? "text-slate-400" : "text-amber-600")} />
            <input
              value={reviewer}
              onChange={(e) => onReviewer(e.target.value)}
              placeholder="Your name"
              className="w-20 bg-transparent text-sm placeholder:text-amber-700/70 focus:outline-none sm:w-32"
            />
          </label>

          <Button variant="primary" icon={<Plus className="size-4" />} onClick={onNewRun}>
            <span className="hidden sm:inline">New triage</span>
          </Button>
        </div>
      </div>
    </header>
  );
}
