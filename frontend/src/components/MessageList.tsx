import { AlertTriangle, Ban, CheckCircle2, Search, XCircle } from "lucide-react";
import { formatWhen } from "../lib/labels";
import type { Item, ReviewStatus } from "../types";
import { IntentChip, cx } from "./ui";

export type StatusFilter = ReviewStatus | "all";

const TABS: { key: StatusFilter; label: string }[] = [
  { key: "pending", label: "To review" },
  { key: "approved", label: "Approved" },
  { key: "rejected", label: "Rejected" },
  { key: "all", label: "All" },
];

export function MessageList({ items, selectedId, onSelect, status, onStatus, statusCounts, query, onQuery, emptyHint }: {
  items: Item[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  status: StatusFilter;
  onStatus: (s: StatusFilter) => void;
  statusCounts: Record<StatusFilter, number>;
  query: string;
  onQuery: (q: string) => void;
  emptyHint: string;
}) {
  return (
    <div className="flex min-h-0 flex-col">
      <div className="space-y-3 border-b border-slate-200/80 p-3">
        <div className="grid grid-cols-4 gap-1 rounded-lg bg-slate-100 p-1">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => onStatus(t.key)}
              className={cx(
                "rounded-md px-1 py-1.5 text-xs font-medium transition-colors",
                status === t.key ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-800",
              )}
            >
              {t.label}
              <span className="ml-1 text-slate-400 tabular-nums">{statusCounts[t.key]}</span>
            </button>
          ))}
        </div>
        <label className="relative block">
          <Search className="pointer-events-none absolute top-2.5 left-3 size-4 text-slate-400" />
          <input
            value={query}
            onChange={(e) => onQuery(e.target.value)}
            placeholder="Search name, subject or text"
            className="h-9 w-full rounded-lg bg-white pr-3 pl-9 text-sm ring-1 ring-slate-200 ring-inset placeholder:text-slate-400 focus:ring-2 focus:ring-indigo-500 focus:outline-none"
          />
        </label>
      </div>

      <ul className="pane min-h-0 flex-1 overflow-y-auto p-2">
        {items.length === 0 && <li className="px-4 py-12 text-center text-sm text-slate-400">{emptyHint}</li>}
        {items.map((it) => {
          const active = it.id === selectedId;
          return (
            <li key={it.id}>
              <button
                onClick={() => onSelect(it.id)}
                className={cx(
                  "relative mb-1 w-full rounded-xl px-3.5 py-3 text-left transition-all",
                  active ? "bg-indigo-50/70 ring-1 ring-indigo-200" : "hover:bg-white hover:shadow-sm hover:ring-1 hover:ring-slate-200",
                )}
              >
                {it.priority_review && it.review_status === "pending" && (
                  <span className="absolute top-3.5 left-1 h-6 w-1 rounded-full bg-rose-400" aria-label="Needs attention" />
                )}
                <div className="flex items-center gap-2">
                  <span className="flex-1 truncate text-sm font-semibold text-slate-900">{it.candidate_name || it.candidate_email || it.message_id}</span>
                  {it.review_status === "approved" && <CheckCircle2 className="size-4 text-emerald-500" />}
                  {it.review_status === "rejected" && <XCircle className="size-4 text-rose-400" />}
                  {it.review_status === "blocked" && <Ban className="size-4 text-zinc-500" />}
                  <span className="text-[11px] whitespace-nowrap text-slate-400 tabular-nums">{formatWhen(it.received_at)}</span>
                </div>
                <div className="mt-0.5 truncate text-[13px] text-slate-700" dir="auto">{it.subject || "(no subject)"}</div>
                <div className="mt-0.5 line-clamp-2 text-[13px] leading-snug text-slate-500" dir="auto">{it.body}</div>
                <div className="mt-2 flex items-center gap-1.5">
                  <IntentChip intent={it.intent} />
                  {it.flags.length > 0 && (
                    <span
                      className={cx(
                        "inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[11px] font-medium",
                        it.priority_review ? "bg-rose-50 text-rose-600" : "bg-slate-100 text-slate-500",
                      )}
                    >
                      {it.priority_review && <AlertTriangle className="size-3" />}
                      {it.flags.length} {it.flags.length === 1 ? "flag" : "flags"}
                    </span>
                  )}
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
