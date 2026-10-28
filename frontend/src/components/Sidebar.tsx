import { AlertTriangle, Ban, Inbox, ShieldAlert } from "lucide-react";
import { INTENT_STYLES, intentLabel } from "../lib/labels";
import type { Item } from "../types";
import { cx } from "./ui";

export type Group = "all" | "attention" | string;

function Row({ active, onClick, icon, label, count, tone }: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  count: number;
  tone?: "alert";
}) {
  return (
    <button
      onClick={onClick}
      className={cx(
        "group flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors",
        active
          ? "bg-white font-medium text-slate-900 shadow-sm ring-1 ring-slate-200"
          : count === 0
            ? "text-slate-400 hover:bg-white/70 hover:text-slate-700"
            : "text-slate-600 hover:bg-white/70 hover:text-slate-900",
      )}
    >
      <span className={cx("grid size-5 place-items-center", count === 0 && !active && "opacity-50")}>{icon}</span>
      <span className="flex-1 truncate">{label}</span>
      <span
        className={cx(
          "min-w-6 rounded-full px-1.5 text-center text-xs tabular-nums",
          tone === "alert" && count > 0 ? "bg-rose-100 font-semibold text-rose-700" : count === 0 ? "text-slate-300" : "text-slate-400",
        )}
      >
        {count}
      </span>
    </button>
  );
}

/** Pending items only drive the "needs attention" count; group counts reflect the chosen status filter. */
export function Sidebar({ items, intents, systemIntents, group, onGroup, blockedCount, onManageBlocklist }: {
  items: Item[];
  intents: string[];
  systemIntents: string[];
  group: Group;
  onGroup: (g: Group) => void;
  blockedCount: number;
  onManageBlocklist: () => void;
}) {
  const attention = items.filter((i) => i.priority_review && i.review_status === "pending").length;
  const counts = new Map<string, number>();
  for (const i of items) counts.set(i.intent, (counts.get(i.intent) ?? 0) + 1);

  return (
    <nav className="pane flex flex-col gap-1 overflow-y-auto p-3">
      <Row active={group === "all"} onClick={() => onGroup("all")} icon={<Inbox className="size-4 text-slate-400" />} label="All messages" count={items.length} />
      <Row
        active={group === "attention"}
        onClick={() => onGroup("attention")}
        icon={<AlertTriangle className="size-4 text-rose-500" />}
        label="Needs attention"
        count={attention}
        tone="alert"
      />
      <div className="mt-4 mb-1 px-2.5 text-[11px] font-semibold tracking-wider text-slate-400 uppercase">What they want</div>
      {intents.map((intent) => (
        <Row
          key={intent}
          active={group === intent}
          onClick={() => onGroup(intent)}
          icon={<span className={cx("size-2 rounded-full", (INTENT_STYLES[intent] ?? INTENT_STYLES.other).dot)} />}
          label={intentLabel(intent)}
          count={counts.get(intent) ?? 0}
        />
      ))}
      <div className="mt-4 mb-1 px-2.5 text-[11px] font-semibold tracking-wider text-slate-400 uppercase">Quarantine</div>
      {systemIntents.map((intent) => (
        <Row
          key={intent}
          active={group === intent}
          onClick={() => onGroup(intent)}
          icon={
            intent === "blocked_sender" ? (
              <Ban className="size-4 text-zinc-600" />
            ) : (
              <ShieldAlert className="size-4 text-red-600" />
            )
          }
          label={intentLabel(intent)}
          count={counts.get(intent) ?? 0}
          tone={intent === "manipulation_attempt" ? "alert" : undefined}
        />
      ))}
      <button
        onClick={onManageBlocklist}
        className="mt-1 rounded-lg px-2.5 py-1.5 text-left text-xs text-slate-500 hover:bg-white/70 hover:text-slate-800"
      >
        Manage blocklist{blockedCount > 0 && <span className="ml-1 text-slate-400">({blockedCount} blocked)</span>}
      </button>
    </nav>
  );
}
