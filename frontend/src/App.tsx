import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, Ban, CheckCircle2, ChevronDown, Clock3, Inbox, Loader2, MousePointerClick, XCircle } from "lucide-react";
import { api } from "./api";
import { BlocklistDialog } from "./components/BlocklistDialog";
import { DetailPanel, type Action } from "./components/DetailPanel";
import { Header } from "./components/Header";
import { MessageList, type StatusFilter } from "./components/MessageList";
import { NewRunDialog, NewRunPanel } from "./components/NewRunDialog";
import { Sidebar, type Group } from "./components/Sidebar";
import { cx } from "./components/ui";
import { INTENT_LABELS, intentLabel } from "./lib/labels";
import type { BlockedSender, Item, Meta, Run } from "./types";

const REVIEWER_KEY = "inbox-helper.reviewer";

function readReviewer() {
  try {
    return localStorage.getItem(REVIEWER_KEY) ?? "";
  } catch {
    return "";
  }
}

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [runId, setRunId] = useState<number | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<Item | null>(null);
  const [group, setGroup] = useState<Group>("all");
  const [status, setStatus] = useState<StatusFilter>("pending");
  const [query, setQuery] = useState("");
  const [reviewer, setReviewer] = useState(readReviewer);
  const [dialog, setDialog] = useState(false);
  const [blocked, setBlocked] = useState<BlockedSender[]>([]);
  const [blocklistOpen, setBlocklistOpen] = useState(false);
  const [toast, setToast] = useState<{ msg: string; tone: "ok" | "error" } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pollKey, setPollKey] = useState(0); // bumped to resume polling after a retry
  const toastTimer = useRef<number | undefined>(undefined);

  const notify = useCallback((msg: string, tone: "ok" | "error" = "ok") => {
    setToast({ msg, tone });
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 2600);
  }, []);

  const updateReviewer = (name: string) => {
    setReviewer(name);
    try {
      localStorage.setItem(REVIEWER_KEY, name);
    } catch {
      /* storage unavailable: name lasts for this session only */
    }
  };

  // initial load; ?run=&item= deep-link to a message
  const linkedItem = useRef<number | null>(Number(new URLSearchParams(location.search).get("item")) || null);
  useEffect(() => {
    Promise.all([api.meta(), api.runs(), api.blocked()])
      .then(([m, r, b]) => {
        setMeta(m);
        setRuns(r);
        setBlocked(b);
        const linked = Number(new URLSearchParams(location.search).get("run"));
        if (r.length) setRunId(r.some((x) => x.id === linked) ? linked : r[0].id);
      })
      .catch((e) => setLoadError((e as Error).message));
  }, []);

  useEffect(() => {
    if (runId == null) return;
    const params = new URLSearchParams({ run: String(runId) });
    if (selectedId != null) params.set("item", String(selectedId));
    history.replaceState(null, "", `?${params}`);
  }, [runId, selectedId]);

  const run = runs?.find((r) => r.id === runId) ?? null;

  const refresh = useCallback(async (id: number) => {
    const [r, its] = await Promise.all([api.run(id), api.items(id)]);
    setRuns((prev) => (prev ? prev.map((x) => (x.id === id ? r : x)) : [r]));
    setItems(its);
    return r;
  }, []);

  useEffect(() => {
    if (runId == null) return;
    setItems([]);
    setSelectedId(linkedItem.current);
    linkedItem.current = null;
  }, [runId]);

  // load items for the chosen run; poll while it is queued or running
  useEffect(() => {
    if (runId == null) return;
    let stop = false;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const r = await refresh(runId);
        if (!stop && isActive(r)) timer = window.setTimeout(tick, 1500);
      } catch (e) {
        if (!stop) notify((e as Error).message, "error");
      }
    };
    tick();
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [runId, pollKey, refresh, notify]);

  const retryRun = async (id: number) => {
    try {
      await api.retry(id);
      notify("Run queued again; messages that already have a draft are kept");
      setPollKey((k) => k + 1);
    } catch (e) {
      notify((e as Error).message, "error");
    }
  };

  // load detail (with history) for the selected item
  useEffect(() => {
    if (selectedId == null) return setDetail(null);
    let live = true;
    api.item(selectedId).then((d) => live && setDetail(d)).catch((e) => notify((e as Error).message, "error"));
    return () => {
      live = false;
    };
  }, [selectedId, notify]);

  const statusCounts = useMemo(() => {
    const c: Record<StatusFilter, number> = { pending: 0, approved: 0, rejected: 0, blocked: 0, all: items.length };
    for (const i of items) c[i.review_status]++;
    return c;
  }, [items]);

  const byStatus = useMemo(() => (status === "all" ? items : items.filter((i) => i.review_status === status)), [items, status]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return byStatus
      .filter((i) => (group === "all" ? true : group === "attention" ? i.priority_review && i.review_status === "pending" : i.intent === group))
      .filter((i) => !q || [i.candidate_name, i.candidate_email, i.subject, i.body, i.message_id].some((f) => f.toLowerCase().includes(q)))
      .sort((a, b) => Number(b.priority_review && b.review_status === "pending") - Number(a.priority_review && a.review_status === "pending") || a.id - b.id);
  }, [byStatus, group, query]);

  const index = visible.findIndex((i) => i.id === selectedId);
  const go = useCallback(
    (delta: number) => {
      const next = visible[index + delta] ?? (index === -1 ? visible[0] : undefined);
      if (next) setSelectedId(next.id);
    },
    [visible, index],
  );

  // J / K keyboard navigation (ignored while typing)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || e.metaKey || e.ctrlKey) return;
      if (e.key === "j") go(1);
      if (e.key === "k") go(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go]);

  const unblock = async (email: string) => {
    try {
      await api.unblock(email, reviewer);
      setBlocked(await api.blocked());
      if (detail) setDetail(await api.item(detail.id));
      notify(`${email} unblocked`);
    } catch (e) {
      notify((e as Error).message, "error");
    }
  };

  const onAction = async (action: Action, payload?: { text?: string; note?: string }) => {
    if (!detail) return;
    if (action === "unblock") return unblock(detail.candidate_email.trim().toLowerCase());
    try {
      const updated =
        action === "regenerate"
          ? await api.regenerate(detail.id, reviewer)
          : action === "block"
            ? await api.block(detail.id, reviewer, payload?.note)
            : await api.review(detail.id, { action, reviewer, ...payload });
      if (action === "block") {
        // blocking closes every pending message from this sender, so reload the list and the blocklist
        setBlocked(await api.blocked());
        if (runId) setItems(await api.items(runId));
      }
      setDetail(updated);
      setItems((prev) => prev.map((i) => (i.id === updated.id ? { ...updated, events: undefined } : i)));
      const messages = {
        save: "Edit saved", approve: "Reply approved", reject: "Draft rejected", reopen: "Reopened for review",
        regenerate: "New draft ready", block: `Blocked ${updated.candidate_email}`, unblock: "",
      };
      notify(messages[action]);
      if (action === "approve" || action === "reject" || action === "block") {
        // move on to the next message still waiting in this view
        const rest = visible.filter((i) => i.id !== updated.id && i.review_status === "pending");
        const after = rest.find((i) => visible.indexOf(i) > index) ?? rest[0];
        if (after && status === "pending") setSelectedId(after.id);
      }
      if (runId) api.run(runId).then((r) => setRuns((prev) => prev?.map((x) => (x.id === r.id ? r : x)) ?? null));
    } catch (e) {
      notify((e as Error).message, "error");
    }
  };

  const onStarted = (id: number) => {
    setDialog(false);
    setStatus("pending");
    setGroup("all");
    api.runs().then((r) => {
      setRuns(r);
      setRunId(id);
    });
  };

  const systemIntents = meta?.system_intents ?? ["manipulation_attempt", "blocked_sender"];
  const intents = (meta ? Object.keys(meta.intents) : Object.keys(INTENT_LABELS)).filter((i) => !systemIntents.includes(i));
  const blockedEmails = useMemo(() => new Set(blocked.map((b) => b.email)), [blocked]);
  const chooseGroup = (g: Group) => {
    setGroup(g);
    if (g === "blocked_sender") setStatus("all"); // blocked messages are closed, so "To review" would hide them
  };

  if (loadError) {
    return (
      <div className="grid h-full place-items-center p-6">
        <div className="flex max-w-md gap-3 rounded-2xl bg-white p-6 text-sm text-slate-600 shadow-sm ring-1 ring-slate-200">
          <AlertCircle className="size-5 shrink-0 text-rose-500" />
          <div>
            <div className="font-semibold text-slate-900">Can't reach the Inbox Helper server</div>
            <p className="mt-1">{loadError}</p>
            <p className="mt-2 text-slate-500">Start it with <code className="rounded bg-slate-100 px-1">uvicorn inbox_helper.server:app</code> and reload.</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-x-hidden">
      <Header
        runs={runs ?? []}
        runId={runId}
        onSelectRun={setRunId}
        reviewer={reviewer}
        onReviewer={updateReviewer}
        onNewRun={() => setDialog(true)}
      />

      {runs === null ? (
        <div className="grid flex-1 place-items-center text-slate-400">
          <Loader2 className="size-6 animate-spin" />
        </div>
      ) : runs.length === 0 ? (
        <div className="grid flex-1 place-items-center p-4">
          <div className="flex w-full max-w-lg flex-col items-center gap-6">
            <div className="text-center">
              <h1 className="text-2xl font-semibold tracking-tight">Clear your candidate inbox, safely</h1>
              <p className="mt-2 text-slate-500">Group messages by what people want, start from an AI draft, and approve every reply yourself.</p>
            </div>
            <NewRunPanel inline onStarted={onStarted} />
          </div>
        </div>
      ) : (
        <>
          {run && <RunBar run={run} counts={statusCounts} onRetry={() => retryRun(run.id)} />}
          <main className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[232px_380px_1fr]">
            <aside className="hidden min-h-0 border-r border-slate-200/80 lg:flex lg:flex-col">
              <Sidebar
                items={byStatus}
                intents={intents}
                systemIntents={systemIntents}
                group={group}
                onGroup={chooseGroup}
                blockedCount={blocked.length}
                onManageBlocklist={() => setBlocklistOpen(true)}
              />
            </aside>

            <section className={cx("min-h-0 flex-col border-r border-slate-200/80 bg-white/40", detail ? "hidden lg:flex" : "flex")}>
              <div className="border-b border-slate-200/80 p-3 lg:hidden">
                <label className="relative block">
                  <select
                    value={group}
                    onChange={(e) => chooseGroup(e.target.value)}
                    className="h-9 w-full appearance-none rounded-lg bg-white px-3 text-sm ring-1 ring-slate-200 ring-inset"
                  >
                    <option value="all">All messages</option>
                    <option value="attention">Needs attention</option>
                    {[...intents, ...systemIntents].map((i) => (
                      <option key={i} value={i}>{intentLabel(i)}</option>
                    ))}
                  </select>
                  <ChevronDown className="pointer-events-none absolute top-2.5 right-2.5 size-4 text-slate-400" />
                </label>
              </div>
              <MessageList
                items={visible}
                selectedId={selectedId}
                onSelect={setSelectedId}
                status={status}
                onStatus={setStatus}
                statusCounts={statusCounts}
                query={query}
                onQuery={setQuery}
                emptyHint={run && isActive(run) && items.length === 0 ? "Drafts will appear here as the AI finishes them…" : "Nothing here. Try another group or tab."}
              />
            </section>

            <section className={cx("min-h-0", detail ? "block" : "hidden lg:block")}>
              {detail ? (
                <DetailPanel
                  key={`${detail.id}:${detail.events?.length ?? 0}:${detail.draft_reply.length}`}
                  item={detail}
                  meta={meta}
                  reviewer={reviewer}
                  blockedEmails={blockedEmails}
                  onAction={onAction}
                  onBack={() => setSelectedId(null)}
                  onPrev={index > 0 ? () => go(-1) : undefined}
                  onNext={index >= 0 && index < visible.length - 1 ? () => go(1) : undefined}
                  notify={notify}
                />
              ) : (
                <div className="grid h-full place-items-center p-8 text-center">
                  <div className="max-w-xs">
                    <div className="mx-auto grid size-12 place-items-center rounded-2xl bg-white text-indigo-500 shadow-sm ring-1 ring-slate-200">
                      <MousePointerClick className="size-5" />
                    </div>
                    <div className="mt-4 font-medium text-slate-800">Pick a message to review</div>
                    <p className="mt-1 text-sm text-slate-500">
                      Start with <span className="font-medium text-rose-600">Needs attention</span>. Use <kbd className="rounded bg-white px-1.5 py-0.5 text-xs ring-1 ring-slate-200">J</kbd> / <kbd className="rounded bg-white px-1.5 py-0.5 text-xs ring-1 ring-slate-200">K</kbd> to move between messages.
                    </p>
                  </div>
                </div>
              )}
            </section>
          </main>
        </>
      )}

      <NewRunDialog open={dialog} onClose={() => setDialog(false)} onStarted={onStarted} />
      <BlocklistDialog
        open={blocklistOpen}
        blocked={blocked}
        reviewer={reviewer}
        onClose={() => setBlocklistOpen(false)}
        onUnblock={unblock}
      />

      {toast && (
        <div className="pointer-events-none fixed inset-x-0 bottom-6 z-50 flex justify-center px-4">
          <div
            className={cx(
              "animate-toast flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-medium text-white shadow-lg",
              toast.tone === "ok" ? "bg-slate-900" : "bg-rose-600",
            )}
          >
            {toast.tone === "ok" ? <CheckCircle2 className="size-4 text-emerald-400" /> : <AlertCircle className="size-4" />}
            {toast.msg}
          </div>
        </div>
      )}
    </div>
  );
}

const isActive = (r: Run) => r.status === "queued" || r.status === "running";

function RunBar({ run, counts, onRetry }: { run: Run; counts: Record<StatusFilter, number>; onRetry: () => void }) {
  const [showErrors, setShowErrors] = useState(false);
  const running = isActive(run);
  const pct = run.total ? Math.round((run.processed / run.total) * 100) : 0;
  const reviewed = counts.approved + counts.rejected + counts.blocked;

  return (
    <div className="border-b border-slate-200/80 bg-white">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 lg:px-6">
        <Stat icon={<Inbox className="size-4 text-slate-400" />} label="Messages" value={run.total} />
        <Stat icon={<AlertCircle className="size-4 text-rose-500" />} label="Need attention" value={run.priority} />
        <Stat icon={<Clock3 className="size-4 text-slate-400" />} label="To review" value={counts.pending} />
        <Stat icon={<CheckCircle2 className="size-4 text-emerald-500" />} label="Approved" value={counts.approved} />
        <Stat icon={<XCircle className="size-4 text-rose-400" />} label="Rejected" value={counts.rejected} />
        {counts.blocked > 0 && <Stat icon={<Ban className="size-4 text-zinc-600" />} label="Blocked" value={counts.blocked} />}

        <div className="flex w-full items-center gap-3 sm:ml-auto sm:w-auto sm:max-w-sm sm:min-w-56 sm:flex-1">
          {running ? (
            <>
              <Loader2 className="size-4 animate-spin text-indigo-500" />
              <div className="flex-1">
                <div className="mb-1 flex justify-between text-xs text-slate-500">
                  <span>{run.status === "queued" ? "Waiting for a worker…" : "AI is drafting replies…"}</span>
                  <span className="tabular-nums">{run.processed}/{run.total}</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
                  <div className="h-full rounded-full bg-indigo-500 transition-all duration-500" style={{ width: `${pct}%` }} />
                </div>
              </div>
            </>
          ) : (
            <div className="flex-1">
              <div className="mb-1 flex justify-between text-xs text-slate-500">
                {run.status === "failed" ? (
                  <span>
                    Run failed: {run.error}{" "}
                    <button onClick={onRetry} className="font-medium text-indigo-600 hover:underline">Retry</button>
                  </span>
                ) : (
                  <span>Review progress</span>
                )}
                <span className="tabular-nums">{reviewed}/{counts.all} reviewed</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
                <div className="h-full rounded-full bg-emerald-500 transition-all duration-500" style={{ width: `${counts.all ? (reviewed / counts.all) * 100 : 0}%` }} />
              </div>
            </div>
          )}
        </div>
      </div>
      {run.input_errors.length > 0 && (
        <div className="border-t border-amber-100 bg-amber-50/70 px-4 py-2 text-xs text-amber-800 lg:px-6">
          <button onClick={() => setShowErrors((v) => !v)} className="font-medium hover:underline">
            {run.input_errors.length} row{run.input_errors.length > 1 ? "s" : ""} in {run.input_name} could not be processed {showErrors ? "▴" : "▾"}
          </button>
          {showErrors && (
            <ul className="mt-1 space-y-0.5">
              {run.input_errors.map((e) => (
                <li key={e.row}>Row {e.row}{e.message_id && ` (${e.message_id})`}: {e.error}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: number }) {
  return (
    <div className="flex items-center gap-2">
      {icon}
      <span className="text-lg font-semibold tabular-nums">{value}</span>
      <span className="text-xs text-slate-500">{label}</span>
    </div>
  );
}
