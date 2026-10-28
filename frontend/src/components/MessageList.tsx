import { useEffect, useRef } from "react";
import { AlertTriangle, Ban, CheckCircle2, ExternalLink, Mail, Search, XCircle } from "lucide-react";
import { gmailThreadUrl } from "./DetailPanel";
import { flagLabel, formatWhen } from "../lib/labels";
import type { Item, ReviewStatus } from "../types";
import { IntentChip, cx } from "./ui";

export type StatusFilter = ReviewStatus | "all";

const TABS: { key: StatusFilter; label: string }[] = [
  { key: "pending", label: "To review" },
  { key: "approved", label: "Approved" },
  { key: "rejected", label: "Rejected" },
  { key: "all", label: "All" },
];

export function MessageList({ items, selectedId, onSelect, status, onStatus, statusCounts, query, onQuery, placeholders, emptyHint }: {
  items: Item[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  status: StatusFilter;
  onStatus: (s: StatusFilter) => void;
  statusCounts: Record<StatusFilter, number>;
  query: string;
  onQuery: (q: string) => void;
  placeholders: number; // drafts still being written: shown as shimmering rows
  emptyHint: string;
}) {
  // keep the selected message visible when it changes from outside the list (J/K, next after approve, a link)
  const list = useRef<HTMLUListElement>(null);
  useEffect(() => {
    list.current?.querySelector(`[data-item="${selectedId}"]`)?.scrollIntoView({ block: "nearest" });
  }, [selectedId]);

  return (
    <div className="flex min-h-0 flex-col">
      <div className="space-y-3 border-b border-slate-200/80 p-3">
        <div className="grid grid-cols-4 gap-1 rounded-lg bg-slate-100 p-1">
          {TABS.map((t) => (
            <button
              key={t.key}
              aria-pressed={status === t.key}
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

      <ul ref={list} className="pane min-h-0 flex-1 overflow-y-auto p-2">
        {items.length === 0 && placeholders === 0 && <li className="px-4 py-12 text-center text-sm text-slate-400">{emptyHint}</li>}
        {items.map((it) => {
          const active = it.id === selectedId;
          const attention = it.priority_review && it.review_status === "pending";
          return (
            <li key={it.id} data-item={it.id} className="animate-row relative scroll-my-2">
              <button
                onClick={() => onSelect(it.id)}
                aria-current={active ? "true" : undefined}
                className={cx(
                  "relative mb-0.5 w-full rounded-lg px-3.5 py-2.5 text-left transition-colors",
                  active ? "bg-indigo-50/80 ring-1 ring-indigo-200" : "hover:bg-white hover:ring-1 hover:ring-slate-200",
                )}
              >
                {attention && (
                  <span className="absolute top-3 left-1 h-5 w-1 rounded-full bg-rose-400" title="Needs attention" aria-label="Needs attention" />
                )}
                <div className="flex items-center gap-2">
                  <span className="flex-1 truncate text-sm font-semibold text-slate-900">{it.candidate_name || it.candidate_email || it.message_id}</span>
                  {it.review_status === "approved" && <CheckCircle2 className="size-4 text-emerald-500" />}
                  {it.review_status === "rejected" && <XCircle className="size-4 text-rose-400" />}
                  {it.review_status === "blocked" && <Ban className="size-4 text-zinc-500" />}
                  <span className="text-[11px] whitespace-nowrap text-slate-400 tabular-nums">{formatWhen(it.received_at)}</span>
                </div>
                <div className="mt-0.5 truncate text-[13px] text-slate-700" dir="auto">
                  {it.subject || "(no subject)"}
                  <span className="text-slate-400"> · {it.body}</span>
                </div>
                <div className="mt-1.5 flex items-center gap-1.5">
                  <IntentChip intent={it.intent} />
                  {it.flags.length > 0 && (
                    <span
                      title={it.flags.map(flagLabel).join(", ")}
                      className="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[11px] text-slate-500"
                    >
                      <AlertTriangle className={cx("size-3", attention ? "text-rose-500" : "text-slate-400")} />
                      {it.flags.length} {it.flags.length === 1 ? "flag" : "flags"}
                    </span>
                  )}
                  {it.gmail && it.review_status === "approved" && (
                    it.gmail.draft_id && !it.gmail.draft_error ? (
                      <span className="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-1.5 py-0.5 text-[11px] font-medium text-emerald-700 ring-1 ring-emerald-200 ring-inset">
                        <Mail className="size-3" /> In Gmail drafts
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-1.5 py-0.5 text-[11px] font-medium text-amber-800 ring-1 ring-amber-200 ring-inset">
                        <AlertTriangle className="size-3" /> No Gmail draft
                      </span>
                    )
                  )}
                </div>
              </button>
              {it.gmail && (
                // a sibling of the row button (a link inside a button is invalid), placed over its chip line
                <a
                  href={gmailThreadUrl(it.gmail.mailbox, it.gmail.thread_id)}
                  target="_blank"
                  rel="noreferrer"
                  title="Open in Gmail"
                  aria-label={`Open ${it.candidate_name || "this message"} in Gmail`}
                  className="absolute right-2.5 bottom-2 grid size-7 place-items-center rounded-md text-slate-400 hover:bg-white hover:text-indigo-600 hover:ring-1 hover:ring-slate-200"
                >
                  <ExternalLink className="size-3.5" />
                </a>
              )}
            </li>
          );
        })}
        {Array.from({ length: placeholders }, (_, i) => (
          <li key={`placeholder-${i}`} className="mb-0.5 rounded-lg px-3.5 py-2.5" aria-hidden>
            <div className="flex items-center gap-2">
              <div className="shimmer h-3.5 w-32 rounded" />
              <div className="shimmer ml-auto h-3 w-16 rounded" />
            </div>
            <div className="shimmer mt-2 h-3 w-full rounded" />
            <div className="shimmer mt-2.5 h-4 w-24 rounded-full" />
          </li>
        ))}
        {placeholders > 0 && <li className="px-4 py-2 text-center text-xs text-slate-400">The AI is drafting the rest…</li>}
      </ul>
    </div>
  );
}
