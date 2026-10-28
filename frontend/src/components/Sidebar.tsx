import { AlertTriangle, Ban, Inbox, MailX, ShieldAlert } from "lucide-react";
import { INTENT_STYLES, intentLabel } from "../lib/labels";
import type { Item } from "../types";
import { cx } from "./ui";

export type Group = "all" | "attention" | string;

/** The AI's suggestion that nobody is waiting for an answer; a reviewer confirms each one. */
export const NO_REPLY = "no_reply_needed";

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
        "relative flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors",
        active
          ? "bg-indigo-50 font-medium text-indigo-700 ring-1 ring-indigo-200/70 ring-inset"
          : count === 0
            ? "text-slate-400 hover:bg-slate-100/70 hover:text-slate-700"
            : "text-slate-600 hover:bg-slate-100/70 hover:text-slate-900",
      )}
    >
      {active && <span className="absolute top-1/2 left-0 h-4 w-[2.5px] -translate-y-1/2 rounded-full bg-indigo-500" />}
      <span className={cx("grid size-5 place-items-center", count === 0 && !active && "opacity-50")}>{icon}</span>
      <span className="flex-1 truncate">{label}</span>
      <span
        className={cx(
          "min-w-6 rounded-full px-1.5 text-center font-mono text-[11.5px] tabular-nums",
          tone === "alert" && count > 0 ? "bg-rose-100 font-semibold text-rose-700" : count === 0 ? "text-slate-300" : "text-slate-400",
        )}
      >
        {count}
      </span>
    </button>
  );
}

/** The groups of the open run, shown in the app sidebar while reviewing. Counts follow the chosen status tab. */
export function Groups({ items, intents, systemIntents, group, onGroup }: {
  items: Item[];
  intents: string[];
  systemIntents: string[];
  group: Group;
  onGroup: (g: Group) => void;
}) {
  const attention = items.filter((i) => i.priority_review && i.review_status === "pending").length;
  const counts = new Map<string, number>();
  for (const i of items) counts.set(i.intent, (counts.get(i.intent) ?? 0) + 1);

  return (
    <div className="space-y-4">
      <div className="space-y-0.5">
        <Row active={group === "all"} onClick={() => onGroup("all")} icon={<Inbox className="size-4 text-slate-400" />} label="All messages" count={items.length} />
        <Row
          active={group === "attention"}
          onClick={() => onGroup("attention")}
          icon={<AlertTriangle className="size-4 text-rose-500" />}
          label="Needs attention"
          count={attention}
          tone="alert"
        />
      </div>
      <div className="space-y-0.5">
        <p className="microlabel mb-1.5 px-2.5">What they want</p>
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
      </div>
      <div className="space-y-0.5">
        <p className="microlabel mb-1.5 px-2.5">AI suggests closing</p>
        <Row
          active={group === NO_REPLY}
          onClick={() => onGroup(NO_REPLY)}
          icon={<MailX className="size-4 text-slate-400" />}
          label={intentLabel(NO_REPLY)}
          count={counts.get(NO_REPLY) ?? 0}
        />
      </div>
      <div className="space-y-0.5">
        <p className="microlabel mb-1.5 px-2.5">Quarantine</p>
        {systemIntents.map((intent) => (
          <Row
            key={intent}
            active={group === intent}
            onClick={() => onGroup(intent)}
            icon={intent === "blocked_sender" ? <Ban className="size-4 text-zinc-600" /> : <ShieldAlert className="size-4 text-red-600" />}
            label={intentLabel(intent)}
            count={counts.get(intent) ?? 0}
            tone={intent === "manipulation_attempt" ? "alert" : undefined}
          />
        ))}
      </div>
    </div>
  );
}
