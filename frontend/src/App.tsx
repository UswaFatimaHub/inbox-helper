import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, AlertTriangle, CheckCircle2, ChevronDown, Loader2, LogIn, MousePointerClick, ShieldCheck, Sparkles, X } from "lucide-react";
import { api, SignedOutError } from "./api";
import { BlocklistDialog } from "./components/BlocklistDialog";
import { DetailPanel, type Action } from "./components/DetailPanel";
import { Header } from "./components/Header";
import { MessageList, type StatusFilter } from "./components/MessageList";
import { NewRunDialog, NewRunPanel } from "./components/NewRunDialog";
import { Sidebar, type Group } from "./components/Sidebar";
import { cx } from "./components/ui";
import { INTENT_LABELS, formatDuration, intentLabel, runSource } from "./lib/labels";
import { useNow } from "./lib/useNow";
import type { BlockedSender, Item, Me, Meta, Run } from "./types";

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
  const [user, setUser] = useState<Me | null>(null);
  const [signedOut, setSignedOut] = useState(false);
  const reviewer = user?.name ?? "";
  const [dialog, setDialog] = useState(false);
  const [blocked, setBlocked] = useState<BlockedSender[]>([]);
  const [blocklistOpen, setBlocklistOpen] = useState(false);
  const [toast, setToast] = useState<{ msg: string; tone: "ok" | "error" } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pollKey, setPollKey] = useState(0); // bumped to resume polling after a retry
  const [finishedRun, setFinishedRun] = useState<number | null>(null); // run that finished while watched
  const toastTimer = useRef<number | undefined>(undefined);

  const notify = useCallback((msg: string, tone: "ok" | "error" = "ok") => {
    setToast({ msg, tone });
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 2600);
  }, []);

  // any API call that gets a 401 (session expired, removed from the allowed list) shows the sign-in screen
  useEffect(() => {
    const onSignedOut = () => setSignedOut(true);
    window.addEventListener("signed-out", onSignedOut);
    return () => window.removeEventListener("signed-out", onSignedOut);
  }, []);

  const signOut = async () => {
    await api.logout();
    setSignedOut(true);
  };

  // initial load; ?run=&item= deep-link to a message
  const linkedItem = useRef<number | null>(Number(new URLSearchParams(location.search).get("item")) || null);
  useEffect(() => {
    Promise.all([api.me(), api.meta(), api.runs(), api.blocked()])
      .then(([u, m, r, b]) => {
        setUser(u);
        setMeta(m);
        setRuns(r);
        setBlocked(b);
        const params = new URLSearchParams(location.search);
        const linked = Number(params.get("run"));
        if (r.length) setRunId(r.some((x) => x.id === linked) ? linked : r[0].id);
        if (params.get("gmail") === "connected") {
          // back from Google's consent screen: offer the fetch straight away
          notify("Gmail connected");
          if (r.length) setDialog(true);
        }
      })
      .catch((e) => {
        if (!(e instanceof SignedOutError)) setLoadError((e as Error).message);
      });
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
    let wasActive = false;
    const tick = async () => {
      try {
        const r = await refresh(runId);
        if (stop) return;
        if (isActive(r)) {
          wasActive = true;
          timer = window.setTimeout(tick, 1500);
        } else if (wasActive && r.status === "done") {
          setFinishedRun(r.id);
        }
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
      await api.unblock(email);
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
          ? await api.regenerate(detail.id)
          : action === "block"
            ? await api.block(detail.id, payload?.note)
            : action === "draft"
              ? await api.gmailDraft(detail.id)
              : await api.review(detail.id, { action, ...payload });
      if (action === "block") {
        // blocking closes every pending message from this sender, so reload the list and the blocklist
        setBlocked(await api.blocked());
        if (runId) setItems(await api.items(runId));
      }
      setDetail(updated);
      setItems((prev) => prev.map((i) => (i.id === updated.id ? { ...updated, events: undefined } : i)));
      const gmail = updated.gmail;
      const messages = {
        save: "Edit saved",
        approve: gmail?.draft_id ? "Reply approved · Gmail draft created" : "Reply approved",
        reject: "Draft rejected",
        reopen: gmail && !gmail.draft_error ? "Reopened for review · Gmail draft deleted" : "Reopened for review",
        regenerate: "New draft ready", block: `Blocked ${updated.candidate_email}`, unblock: "", draft: "Gmail draft created",
      };
      if (gmail?.draft_error && (action === "approve" || action === "reopen" || action === "draft")) {
        notify(action === "approve" ? `Approved, but the Gmail draft failed: ${gmail.draft_error}` : gmail.draft_error, "error");
      } else {
        notify(messages[action]);
      }
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
  const showAttention = () => {
    setGroup("attention");
    setStatus("pending");
    setFinishedRun(null);
  };
  // placeholder rows for drafts still being written (only in views where new drafts would show up)
  const placeholders = run && isActive(run) && status !== "approved" && status !== "rejected" && group === "all" && !query
    ? Math.min(3, run.total - run.processed)
    : 0;

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

  if (signedOut) return <SignIn />;

  return (
    <div className="flex h-full flex-col overflow-x-hidden">
      <Header
        runs={runs ?? []}
        runId={runId}
        onSelectRun={setRunId}
        user={user}
        onSignOut={signOut}
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
          {run && <RunBar run={run} counts={statusCounts} onRetry={() => retryRun(run.id)} onAttention={showAttention} />}
          {run && finishedRun === run.id && <ReadyBanner run={run} onAttention={showAttention} onClose={() => setFinishedRun(null)} />}
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
                placeholders={placeholders}
                emptyHint="Nothing here. Try another group or tab."
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

function RunBar({ run, counts, onRetry, onAttention }: {
  run: Run;
  counts: Record<StatusFilter, number>;
  onRetry: () => void;
  onAttention: () => void;
}) {
  const [showErrors, setShowErrors] = useState(false);

  return (
    <div className="border-b border-slate-200/80 bg-white">
      {isActive(run) ? <RunProgress run={run} /> : <ReviewSummary run={run} counts={counts} onRetry={onRetry} onAttention={onAttention} />}
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

const RUN_STEPS = [
  { key: "queued", label: "Queued" },
  { key: "running", label: "Reading & drafting" },
  { key: "done", label: "Ready to review" },
] as const;

/** While the AI works: what stage it is at, how far along, how long it has taken and roughly how long is left. */
function RunProgress({ run }: { run: Run }) {
  const now = useNow(true);
  const elapsed = Math.max(0, (now - new Date(run.created_at).getTime()) / 1000);
  const pct = run.total ? (run.processed / run.total) * 100 : 0;
  // estimate only once a few drafts are in; batches arrive in bursts, so earlier guesses swing wildly
  const left = run.processed >= 3 && run.processed < run.total ? ((run.total - run.processed) * elapsed) / run.processed : null;
  const quarantined = run.by_intent.manipulation_attempt ?? 0;
  const step = run.status === "queued" ? 0 : 1;

  return (
    <div className="px-4 py-4 lg:px-6" aria-live="polite">
      <div className="flex flex-wrap items-start gap-x-6 gap-y-3">
        <div className="flex min-w-0 flex-1 items-start gap-3">
          <div className="grid size-9 shrink-0 place-items-center rounded-full bg-indigo-50 text-indigo-600 ring-1 ring-indigo-100">
            <Sparkles className="size-4" />
          </div>
          <div className="min-w-0">
            <div className="text-sm font-semibold text-slate-900">
              {run.status === "queued" ? "Getting ready…" : `Drafting replies · ${run.processed} of ${run.total}`}
            </div>
            <div className="mt-0.5 text-xs text-slate-500">
              {run.status === "queued"
                ? `${run.total} messages from ${runSource(run.input_name)} are waiting for the AI.`
                : run.processed === 0
                  ? "The AI is reading the first messages."
                  : `So far ${run.priority} need${run.priority === 1 ? "s" : ""} attention${quarantined ? ` · ${quarantined} quarantined` : ""}. You can start reviewing as drafts arrive.`}
            </div>
          </div>
        </div>
        <ol className="hidden items-center gap-1.5 text-xs md:flex">
          {RUN_STEPS.map((s, i) => (
            <li key={s.key} className="flex items-center gap-1.5">
              {i > 0 && <span className="h-px w-4 bg-slate-200" />}
              <span
                className={cx(
                  "inline-flex items-center gap-1 rounded-full px-2 py-0.5",
                  i < step ? "text-emerald-700" : i === step ? "bg-indigo-50 font-medium text-indigo-700 ring-1 ring-indigo-200" : "text-slate-400",
                )}
              >
                {i < step && <CheckCircle2 className="size-3.5" />}
                {i === step && <Loader2 className="size-3.5 animate-spin" />}
                {s.label}
              </span>
            </li>
          ))}
        </ol>
        <div className="text-right text-xs text-slate-500 tabular-nums">
          <div className="font-medium text-slate-700">{formatDuration(elapsed)}</div>
          <div>{left != null ? `about ${formatDuration(left)} left` : "elapsed"}</div>
        </div>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100">
        {run.status === "queued" || run.processed === 0 ? (
          <div className="animate-indeterminate h-full w-2/5 rounded-full bg-indigo-400" />
        ) : (
          <div className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 transition-all duration-700" style={{ width: `${pct}%` }} />
        )}
      </div>
    </div>
  );
}

/** After the run: review progress as one stacked bar, and a way straight to what needs attention. */
function ReviewSummary({ run, counts, onRetry, onAttention }: {
  run: Run;
  counts: Record<StatusFilter, number>;
  onRetry: () => void;
  onAttention: () => void;
}) {
  const reviewed = counts.approved + counts.rejected + counts.blocked;
  const share = (n: number) => `${counts.all ? (n / counts.all) * 100 : 0}%`;

  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5 lg:px-6">
      <div className="min-w-0 text-sm text-slate-500">
        <span className="font-medium text-slate-800">{run.total} messages</span>
        {run.elapsed_s != null && <span> · drafted in {formatDuration(run.elapsed_s)}</span>}
      </div>
      {run.status === "failed" && (
        <div className="flex items-center gap-2 text-xs text-rose-700">
          <AlertCircle className="size-4" /> Run failed: {run.error}
          <button onClick={onRetry} className="font-medium text-indigo-600 hover:underline">Retry</button>
        </div>
      )}
      <div className="flex min-w-60 flex-1 items-center gap-3 sm:ml-auto sm:max-w-md">
        <div
          className="flex h-2 flex-1 overflow-hidden rounded-full bg-slate-100"
          title={`${counts.approved} approved · ${counts.rejected} rejected · ${counts.blocked} blocked · ${counts.pending} to review`}
        >
          <div className="bg-emerald-500 transition-all duration-500" style={{ width: share(counts.approved) }} />
          <div className="bg-rose-300 transition-all duration-500" style={{ width: share(counts.rejected) }} />
          <div className="bg-zinc-500 transition-all duration-500" style={{ width: share(counts.blocked) }} />
        </div>
        <span className="text-xs whitespace-nowrap text-slate-500 tabular-nums">
          {reviewed} of {counts.all} reviewed
        </span>
      </div>
      {run.priority > 0 && (
        <button
          onClick={onAttention}
          className="inline-flex items-center gap-1.5 rounded-full bg-rose-50 px-2.5 py-1 text-xs font-medium text-rose-700 ring-1 ring-rose-200 hover:bg-rose-100"
        >
          <AlertTriangle className="size-3.5" /> {run.priority} need attention
        </button>
      )}
    </div>
  );
}

/** Shown once when the run being watched finishes. */
function ReadyBanner({ run, onAttention, onClose }: { run: Run; onAttention: () => void; onClose: () => void }) {
  return (
    <div className="animate-row flex flex-wrap items-center gap-3 border-b border-emerald-100 bg-emerald-50/70 px-4 py-2.5 text-sm text-emerald-900 lg:px-6">
      <CheckCircle2 className="size-4 text-emerald-600" />
      <span className="flex-1">
        <span className="font-medium">All {run.total} drafts are ready</span>
        {run.elapsed_s != null && <span className="text-emerald-800/80"> · took {formatDuration(run.elapsed_s)}</span>}
        {run.priority > 0 && <span className="text-emerald-800/80"> · {run.priority} need your attention first</span>}
      </span>
      {run.priority > 0 && (
        <button onClick={onAttention} className="rounded-lg bg-white px-2.5 py-1 text-xs font-medium text-emerald-800 ring-1 ring-emerald-200 hover:bg-emerald-50">
          Review those first
        </button>
      )}
      <button onClick={onClose} className="rounded p-1 text-emerald-700/70 hover:bg-emerald-100 hover:text-emerald-900" aria-label="Dismiss">
        <X className="size-4" />
      </button>
    </div>
  );
}

function SignIn() {
  return (
    <div className="grid h-full place-items-center p-4">
      <div className="flex w-full max-w-sm flex-col items-center gap-5 rounded-2xl bg-white p-8 text-center shadow-sm ring-1 ring-slate-200">
        <div className="grid size-11 place-items-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-md shadow-indigo-500/25">
          <ShieldCheck className="size-6" strokeWidth={2.2} />
        </div>
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Inbox Helper</h1>
          <p className="mt-1 text-sm text-slate-500">Sign in with the Google account your team added to the reviewer list.</p>
        </div>
        <a
          href={api.loginUrl}
          className="flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 text-sm font-medium text-white hover:bg-indigo-500"
        >
          <LogIn className="size-4" /> Sign in with Google
        </a>
        <p className="text-xs text-slate-400">Your account is recorded on every approval, edit and rejection.</p>
      </div>
    </div>
  );
}
