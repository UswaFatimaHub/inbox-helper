import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle, AlertTriangle, ArrowRight, CheckCircle2, ChevronDown, Download, Keyboard, Loader2, LogIn, MousePointerClick,
  Sparkles, X,
} from "lucide-react";
import { api, SignedOutError } from "./api";
import { BlocklistDialog } from "./components/BlocklistDialog";
import { SignatureDialog } from "./components/SignatureDialog";
import { DetailPanel, NO_REPLY_NOTE, type Action } from "./components/DetailPanel";
import { MessageList, type StatusFilter } from "./components/MessageList";
import { LogoMark, Shell, type Page } from "./components/Shell";
import { Groups, NO_REPLY, type Group } from "./components/Sidebar";
import { cx } from "./components/ui";
import { INTENT_LABELS, formatDuration, intentLabel } from "./lib/labels";
import { useNow } from "./lib/useNow";
import { Overview, type QueueView } from "./pages/Overview";
import type { BlockedSender, GmailStatus, Item, Me, Meta, Run } from "./types";

/** Page from the address bar: "/" is the overview, "?view=queue&item=12" the review queue. */
function readLocation() {
  const params = new URLSearchParams(location.search);
  const item = Number(params.get("item")) || null;
  return { page: (params.get("view") === "queue" || item ? "review" : "home") as Page, item };
}

const isActive = (r: Run) => r.status === "queued" || r.status === "running";

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [items, setItems] = useState<Item[] | null>(null);
  const [page, setPage] = useState<Page>(() => readLocation().page);
  const [selectedId, setSelectedId] = useState<number | null>(() => readLocation().item);
  const [detail, setDetail] = useState<Item | null>(null);
  const [group, setGroup] = useState<Group>("all");
  const [status, setStatus] = useState<StatusFilter>("pending");
  const [query, setQuery] = useState("");
  const [user, setUser] = useState<Me | null>(null);
  const [signedOut, setSignedOut] = useState(false);
  const reviewer = user?.name ?? "";
  const [gmail, setGmail] = useState<GmailStatus | null>(null);
  const [blocked, setBlocked] = useState<BlockedSender[]>([]);
  const [blocklistOpen, setBlocklistOpen] = useState(false);
  const [signatureOpen, setSignatureOpen] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);
  const [shortcuts, setShortcuts] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [finished, setFinished] = useState<{ count: number; seconds: number } | null>(null); // drafting just ended
  const toastTimer = useRef<number | undefined>(undefined);

  const notify = useCallback((msg: string, tone: "ok" | "error" = "ok", action?: Toast["action"]) => {
    setToast({ msg, tone, action });
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), action ? 5000 : 3200);
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

  const loadGmail = useCallback(() => {
    api.gmailStatus().then(setGmail).catch(() => setGmail(null));
  }, []);

  const reload = useCallback(async () => {
    const [r, its] = await Promise.all([api.runs(), api.queue()]);
    setRuns(r);
    setItems(its);
    return r;
  }, []);

  useEffect(() => {
    Promise.all([api.me(), api.meta(), api.blocked(), reload()])
      .then(([u, m, b]) => {
        setUser(u);
        setMeta(m);
        setBlocked(b);
        if (new URLSearchParams(location.search).get("gmail") === "connected") {
          notify("Gmail connected · fetch new emails when you're ready"); // back from Google's consent screen
          setPage("home");
        }
      })
      .catch((e) => {
        if (!(e instanceof SignedOutError)) setLoadError((e as Error).message);
      });
    loadGmail();
  }, []);

  // while anything is being drafted, refresh the queue so new drafts show up as they finish
  const active = useMemo(() => runs.filter(isActive), [runs]);
  const watching = useRef<Run[]>([]); // the batches being drafted, kept after they finish for the ready banner
  useEffect(() => {
    if (active.length) watching.current = active;
  }, [active]);
  useEffect(() => {
    if (!active.length) return;
    let live = true;
    const t = window.setInterval(async () => {
      try {
        const r = await reload();
        if (!live || r.some(isActive)) return;
        const done = r.filter((x) => watching.current.some((w) => w.id === x.id) && x.status === "done");
        if (done.length) setFinished({ count: done.reduce((n, x) => n + x.total, 0), seconds: Math.max(...done.map((x) => x.elapsed_s ?? 0)) });
      } catch (e) {
        if (live) notify((e as Error).message, "error");
      }
    }, 1500);
    return () => {
      live = false;
      window.clearInterval(t);
    };
  }, [active.length > 0, reload, notify]);

  // keep the address bar in step: a new page is a history entry, a new message is not
  const shownPage = useRef(page);
  useEffect(() => {
    const params = new URLSearchParams();
    if (page === "review") {
      params.set("view", "queue");
      if (selectedId != null) params.set("item", String(selectedId));
    }
    const url = params.size ? `?${params}` : location.pathname;
    if (shownPage.current !== page) history.pushState(null, "", url);
    else history.replaceState(null, "", url);
    shownPage.current = page;
  }, [page, selectedId]);

  useEffect(() => {
    const onPop = () => {
      const loc = readLocation();
      shownPage.current = loc.page;
      setPage(loc.page);
      setSelectedId(loc.item);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // load detail (with history) for the selected item
  useEffect(() => {
    if (selectedId == null) return setDetail(null);
    let live = true;
    api.item(selectedId).then((d) => live && setDetail(d)).catch((e) => notify((e as Error).message, "error"));
    return () => {
      live = false;
    };
  }, [selectedId, notify]);

  const all = items ?? [];
  const statusCounts = useMemo(() => {
    const c: Record<StatusFilter, number> = { pending: 0, approved: 0, rejected: 0, blocked: 0, all: all.length };
    for (const i of all) c[i.review_status]++;
    return c;
  }, [all]);

  const byStatus = useMemo(() => (status === "all" ? all : all.filter((i) => i.review_status === status)), [all, status]);

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
    if (page !== "review") return;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || e.metaKey || e.ctrlKey) return;
      if (e.key === "?") setShortcuts((v) => !v);
      else if (e.key === "Escape") setShortcuts(false);
      else if (shortcuts) return;
      else if (e.key === "j") go(1);
      else if (e.key === "k") go(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, page, shortcuts]);

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
        // blocking closes every pending message from this sender, so reload the queue and the blocklist
        setBlocked(await api.blocked());
        setItems(await api.queue());
      }
      setDetail(updated);
      setItems((prev) => prev?.map((i) => (i.id === updated.id ? { ...updated, events: undefined } : i)) ?? null);
      const gm = updated.gmail;
      const messages = {
        save: "Edit saved",
        approve: gm?.draft_id ? "Reply approved · Gmail draft created" : "Reply approved",
        reject: payload?.note === NO_REPLY_NOTE ? "Closed without a reply" : "Draft rejected",
        reopen: gm && !gm.draft_error ? "Reopened for review · Gmail draft deleted" : "Reopened for review",
        regenerate: "New draft ready", block: `Blocked ${updated.candidate_email}`, unblock: "", draft: "Gmail draft created",
      };
      if (gm?.draft_error && (action === "approve" || action === "reopen" || action === "draft")) {
        notify(action === "approve" ? `Approved, but the Gmail draft failed: ${gm.draft_error}` : gm.draft_error, "error",
          action === "approve" ? { label: "Undo", run: () => undo(updated.id) } : undefined);
      } else if (action === "approve" || action === "reject") {
        notify(messages[action], "ok", { label: "Undo", run: () => undo(updated.id) });
      } else {
        notify(messages[action]);
      }
      if (action === "approve" || action === "reject" || action === "block") {
        // move on to the next message still waiting in this view
        const rest = visible.filter((i) => i.id !== updated.id && i.review_status === "pending");
        const after = rest.find((i) => visible.indexOf(i) > index) ?? rest[0];
        if (after && status === "pending") setSelectedId(after.id);
      }
    } catch (e) {
      notify((e as Error).message, "error");
    }
  };

  /** Undo an approve or reject: the message goes back to "to review" (and its Gmail draft is deleted). */
  const undo = async (id: number) => {
    setToast(null);
    try {
      const back = await api.review(id, { action: "reopen" });
      setItems((prev) => prev?.map((i) => (i.id === id ? { ...back, events: undefined } : i)) ?? null);
      setSelectedId(id);
      setDetail(back);
      notify("Undone · back in the queue");
    } catch (e) {
      notify((e as Error).message, "error");
    }
  };

  const openQueue = (view: QueueView) => {
    setGroup(view.group);
    setStatus(view.status);
    setQuery("");
    setSelectedId(null);
    setFinished(null);
    setPage("review");
  };

  const onStarted = (summary: string) => {
    notify(summary);
    setFinished(null);
    reload().catch(() => undefined);
  };

  const retry = async (id: number) => {
    try {
      await api.retry(id);
      notify("Queued again; messages that already have a draft are kept");
      await reload();
    } catch (e) {
      notify((e as Error).message, "error");
    }
  };

  const systemIntents = meta?.system_intents ?? ["manipulation_attempt", "blocked_sender"];
  const intents = (meta ? Object.keys(meta.intents) : Object.keys(INTENT_LABELS)).filter((i) => !systemIntents.includes(i) && i !== NO_REPLY);
  const blockedEmails = useMemo(() => new Set(blocked.map((b) => b.email)), [blocked]);
  const chooseGroup = (g: Group) => {
    setGroup(g);
    if (g === "blocked_sender") setStatus("all"); // blocked messages are closed, so "To review" would hide them
  };
  const latestFailed = runs[0]?.status === "failed" ? runs[0] : null;
  // placeholder rows for drafts still being written (only in views where new drafts would show up)
  const remaining = active.reduce((n, r) => n + r.total - r.processed, 0);
  const placeholders = status !== "approved" && status !== "rejected" && group === "all" && !query ? Math.min(3, remaining) : 0;

  const banners = (
    <>
      {active.length > 0 && <Drafting runs={active} onReview={() => openQueue({ group: "all", status: "pending" })} />}
      {finished && !active.length && <ReadyBanner {...finished} onReview={() => openQueue({ group: "all", status: "pending" })} onClose={() => setFinished(null)} />}
      {latestFailed && !active.length && (
        <div className="flex items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 px-4 py-2.5 text-sm text-rose-800">
          <AlertCircle className="size-4" /> The last batch stopped: {latestFailed.error}
          <button onClick={() => retry(latestFailed.id)} className="ml-auto font-medium text-indigo-700 hover:underline">Try again</button>
        </div>
      )}
    </>
  );

  if (loadError) {
    return (
      <div className="grid h-full place-items-center p-6">
        <div className="card flex max-w-md gap-3 p-6 text-sm text-slate-600">
          <AlertCircle className="size-5 shrink-0 text-rose-500" />
          <div>
            <div className="font-semibold text-slate-900">Can't reach the Inbox Helper server</div>
            <p className="mt-1">{loadError}</p>
            <p className="mt-2 text-slate-500">Start it with <code className="rounded bg-slate-100 px-1 font-mono">uvicorn inbox_helper.server:app</code> and reload.</p>
          </div>
        </div>
      </div>
    );
  }

  if (signedOut) return <SignIn />;

  if (items === null) {
    return (
      <div className="grid h-full place-items-center text-slate-400">
        <Loader2 className="size-6 animate-spin" />
      </div>
    );
  }

  return (
    <>
      <Shell
        page={page}
        onPage={(p) => (p === "review" ? openQueue({ group: "all", status: "pending" }) : setPage(p))}
        toReview={statusCounts.pending}
        groups={<Groups items={byStatus} intents={intents} systemIntents={systemIntents} group={group} onGroup={chooseGroup} />}
        blockedCount={blocked.length}
        onBlocklist={() => setBlocklistOpen(true)}
        onSignature={() => setSignatureOpen(true)}
        gmail={gmail}
        user={user}
        onSignOut={signOut}
      >
        {page === "home" ? (
          <Overview
            items={all}
            intents={intents}
            drafting={banners}
            gmail={gmail}
            onGmailChange={loadGmail}
            onStarted={onStarted}
            onOpen={openQueue}
          />
        ) : (
          <div className="flex h-full flex-col">
            <div className={cx(detail && "hidden lg:block")}>
            <QueueBar counts={statusCounts} attention={all.filter((i) => i.priority_review && i.review_status === "pending").length}
              onAttention={() => openQueue({ group: "attention", status: "pending" })} onShortcuts={() => setShortcuts(true)} />
            {(active.length > 0 || finished || latestFailed) && <div className="space-y-2 border-b border-slate-200/80 px-4 py-3 lg:px-6">{banners}</div>}
            </div>
            <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[380px_1fr]">
              <section className={cx("min-h-0 flex-col border-r border-slate-200/80 bg-white/60", detail ? "hidden lg:flex" : "flex")}>
                <div className="border-b border-slate-200/80 p-3 lg:hidden">
                  <label className="relative block">
                    <select
                      value={group}
                      onChange={(e) => chooseGroup(e.target.value)}
                      className="h-9 w-full appearance-none rounded-lg bg-white px-3 text-sm ring-1 ring-slate-200 ring-inset"
                    >
                      <option value="all">All messages</option>
                      <option value="attention">Needs attention</option>
                      {[...intents, NO_REPLY, ...systemIntents].map((i) => (
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
                  emptyHint={all.length ? "Nothing here. Try another group or tab." : "The queue is empty. Fetch emails or drop a file on the overview."}
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
                      <div className="mx-auto grid size-12 place-items-center rounded-2xl border border-indigo-200 bg-indigo-50/80 text-indigo-600">
                        <MousePointerClick className="size-5" />
                      </div>
                      <div className="mt-4 font-medium text-slate-800">Pick a message to review</div>
                      <p className="mt-1 text-sm text-slate-500">
                        Start with <span className="font-medium text-rose-600">Needs attention</span>. Use <Kbd>J</Kbd> / <Kbd>K</Kbd> to move between messages.
                      </p>
                    </div>
                  </div>
                )}
              </section>
            </div>
          </div>
        )}
      </Shell>

      <SignatureDialog
        open={signatureOpen}
        onClose={() => setSignatureOpen(false)}
        onSaved={async () => {
          // drafts are shown with the reviewer's signature, so fetch them again
          await reload();
          if (selectedId != null) setDetail(await api.item(selectedId));
          notify("Signature saved · drafts updated");
        }}
      />
      <BlocklistDialog
        open={blocklistOpen}
        blocked={blocked}
        reviewer={reviewer}
        onClose={() => setBlocklistOpen(false)}
        onUnblock={unblock}
      />

      {toast && (
        <div className="pointer-events-none fixed inset-x-0 bottom-6 z-50 flex justify-center px-4" role="status" aria-live="polite">
          <div
            className={cx(
              "animate-toast pointer-events-auto flex items-center gap-2 rounded-xl py-2.5 pr-2.5 pl-4 text-sm font-medium shadow-lg",
              toast.tone === "ok" ? "bg-slate-900 text-slate-50" : "bg-rose-600 text-on-accent",
            )}
          >
            {toast.tone === "ok" ? <CheckCircle2 className="size-4 text-emerald-400" /> : <AlertCircle className="size-4" />}
            <span className="pr-1.5">{toast.msg}</span>
            {toast.action && (
              <button
                onClick={toast.action.run}
                className="rounded-md px-2 py-0.5 font-semibold text-indigo-300 ring-1 ring-slate-600 hover:bg-slate-800 hover:text-indigo-200"
              >
                {toast.action.label}
              </button>
            )}
          </div>
        </div>
      )}

      {shortcuts && <Shortcuts onClose={() => setShortcuts(false)} />}
    </>
  );
}

type Toast = { msg: string; tone: "ok" | "error"; action?: { label: string; run: () => void } };

const SHORTCUTS: [string[], string][] = [
  [["J"], "Next message"],
  [["K"], "Previous message"],
  [["A"], "Approve the reply"],
  [["Ctrl", "Enter"], "Approve while typing in the reply"],
  [["R"], "Reject (asks for an optional reason). On a no-reply or quarantined message: close it"],
  [["E"], "Edit the reply (also writes one for a no-reply or quarantined message)"],
  [["Esc"], "Cancel the reject box, close this list"],
  [["?"], "Show or hide this list"],
];

/** "?" overlay: every keyboard shortcut of the review queue. */
function Shortcuts({ onClose }: { onClose: () => void }) {
  return (
    <div data-overlay className="fixed inset-0 z-50 grid place-items-center bg-slate-900/30 p-4 backdrop-blur-sm" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcuts-title"
        onMouseDown={(e) => e.stopPropagation()}
        className="card corners w-full max-w-md p-6 shadow-pop"
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <p className="microlabel !text-indigo-500/80">Review queue</p>
            <h2 id="shortcuts-title" className="mt-1 text-lg font-semibold tracking-tight">Keyboard shortcuts</h2>
          </div>
          <button onClick={onClose} aria-label="Close" className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600">
            <X className="size-5" />
          </button>
        </div>
        <dl className="divide-y divide-slate-100">
          {SHORTCUTS.map(([keys, what]) => (
            <div key={what} className="flex items-start gap-4 py-2.5">
              <dt className="flex w-28 shrink-0 flex-wrap items-center gap-1">
                {keys.map((k, i) => (
                  <span key={k} className="flex items-center gap-1">
                    {i > 0 && <span className="text-xs text-slate-400">+</span>}
                    <Kbd>{k}</Kbd>
                  </span>
                ))}
              </dt>
              <dd className="text-sm text-slate-600">{what}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-4 text-xs text-slate-500">Shortcuts pause while you type in a box. Approve and reject can be undone from the message that pops up.</p>
      </div>
    </div>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return <kbd className="rounded border border-slate-200 bg-white px-1.5 py-0.5 font-mono text-xs text-slate-600 shadow-[0_1px_0_rgba(0,0,0,0.08)]">{children}</kbd>;
}

/** Top of the queue: how much of it is reviewed, what needs attention, and the export. */
function QueueBar({ counts, attention, onAttention, onShortcuts }: {
  counts: Record<StatusFilter, number>;
  attention: number;
  onAttention: () => void;
  onShortcuts: () => void;
}) {
  const reviewed = counts.approved + counts.rejected + counts.blocked;
  const share = (n: number) => `${counts.all ? (n / counts.all) * 100 : 0}%`;

  return (
    <div className="relative z-20 flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-slate-200/80 bg-white/75 px-4 py-3 backdrop-blur-sm lg:px-6">
      <div className="min-w-0">
        <p className="microlabel">Candidate inbox</p>
        <p className="text-[15px] font-semibold tracking-tight text-slate-900">
          Review queue <span className="font-normal text-slate-400">· {counts.pending} waiting<span className="hidden sm:inline"> · {counts.all} in total</span></span>
        </p>
      </div>
      <div className="ml-auto flex items-center gap-3">
        <div
          tabIndex={0}
          aria-label={`${reviewed} of ${counts.all} reviewed. Hover or focus for the breakdown.`}
          className="group relative hidden w-48 cursor-default items-center gap-2 rounded-md py-1 md:flex"
        >
          <div className="flex h-1.5 flex-1 gap-px overflow-hidden rounded-full bg-slate-100">
            <div className="bg-emerald-500 transition-all duration-500" style={{ width: share(counts.approved) }} />
            <div className="bg-rose-300 transition-all duration-500" style={{ width: share(counts.rejected) }} />
            <div className="bg-zinc-500 transition-all duration-500" style={{ width: share(counts.blocked) }} />
          </div>
          <span className="font-mono text-xs whitespace-nowrap text-slate-500 tabular-nums">
            {reviewed}/{counts.all}
          </span>
          <div className="card invisible absolute top-full right-0 z-30 mt-2 w-80 !bg-white p-4 opacity-0 shadow-pop transition-opacity group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100">
            <div className="flex items-baseline justify-between">
              <p className="microlabel">Review progress</p>
              <span className="font-mono text-xs text-slate-500 tabular-nums">{reviewed} of {counts.all} done</span>
            </div>
            <ul className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
              {([["Approved", counts.approved, "bg-emerald-500"], ["Closed", counts.rejected, "bg-rose-300"],
                 ["Blocked", counts.blocked, "bg-zinc-500"], ["To review", counts.pending, "bg-slate-200"]] as const).map(([label, n, swatch]) => (
                <li key={label} className="flex items-center gap-2">
                  <span className={cx("size-2.5 rounded-sm", swatch)} />
                  <span className="flex-1 truncate text-slate-600">{label}</span>
                  <span className="font-mono text-slate-800 tabular-nums">{n}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
        {attention > 0 && (
          <button
            onClick={onAttention}
            className="inline-flex items-center gap-1.5 rounded-lg border border-rose-200 bg-rose-50 px-2.5 py-1 text-xs font-medium text-rose-700 hover:bg-rose-100"
          >
            <AlertTriangle className="size-3.5" /> {attention}<span className="hidden sm:inline"> need attention</span>
          </button>
        )}
        <button
          onClick={onShortcuts}
          title="Keyboard shortcuts (?)"
          aria-label="Keyboard shortcuts"
          className="hidden size-8 place-items-center rounded-lg text-slate-500 ring-1 ring-slate-200 hover:bg-white hover:text-slate-900 md:grid"
        >
          <Keyboard className="size-4" />
        </button>
        <a
          href={api.exportUrl}
          title="Download every approved reply as CSV"
          aria-label="Export approved replies as CSV"
          className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[13px] font-medium text-slate-600 ring-1 ring-slate-200 hover:bg-white hover:text-slate-900"
        >
          <Download className="size-3.5" /> <span className="hidden sm:inline">Export approved</span>
        </a>
      </div>
    </div>
  );
}

const STEPS = [
  { key: "queued", label: "Queued" },
  { key: "running", label: "Reading & drafting" },
  { key: "done", label: "In the queue" },
] as const;

/** While the AI works on new messages: stage, how far along, time taken and roughly how long is left. */
function Drafting({ runs, onReview }: { runs: Run[]; onReview: () => void }) {
  const now = useNow(true);
  const total = runs.reduce((n, r) => n + r.total, 0);
  const processed = runs.reduce((n, r) => n + r.processed, 0);
  const attention = runs.reduce((n, r) => n + r.priority, 0);
  const quarantined = runs.reduce((n, r) => n + (r.by_intent.manipulation_attempt ?? 0), 0);
  const queued = runs.every((r) => r.status === "queued");
  const started = Math.min(...runs.map((r) => new Date(r.created_at).getTime()));
  const elapsed = Math.max(0, (now - started) / 1000);
  // estimate only once a few drafts are in; batches arrive in bursts, so earlier guesses swing wildly
  const left = processed >= 3 && processed < total ? ((total - processed) * elapsed) / processed : null;
  const step = queued ? 0 : 1;
  const sorted = new Map<string, number>();
  for (const r of runs) for (const [intent, n] of Object.entries(r.by_intent)) sorted.set(intent, (sorted.get(intent) ?? 0) + n);
  const tally = [...sorted.entries()].sort((a, b) => b[1] - a[1]);

  return (
    <div className="card p-4" aria-live="polite">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <Sparkles className="size-4 shrink-0 text-indigo-500" />
          <div className="min-w-0 text-sm">
            <span className="font-medium text-slate-900">
              {queued ? `Getting ready · ${total} new message${total === 1 ? "" : "s"}` : `Drafting replies · ${processed} of ${total} new`}
            </span>
            {!queued && processed > 0 && (
              <span className="text-slate-500"> · {attention} need{attention === 1 ? "s" : ""} attention{quarantined ? ` · ${quarantined} quarantined` : ""}</span>
            )}
          </div>
        </div>
        <ol className="hidden items-center gap-1.5 md:flex">
          {STEPS.map((s, i) => (
            <li key={s.key} className="flex items-center gap-1.5">
              {i > 0 && <span className="h-px w-4 bg-slate-200" />}
              <span
                className={cx(
                  "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-mono text-[11px] tracking-[0.06em] uppercase",
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
        <div className="font-mono text-xs text-slate-500 tabular-nums">
          {formatDuration(elapsed)}
          {left != null && <span className="text-slate-400"> · ~{formatDuration(left)} left</span>}
        </div>
      </div>
      <div
        className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100"
        role="progressbar"
        aria-label="Drafting progress"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={processed}
      >
        {queued || processed === 0 ? (
          <div className="animate-indeterminate h-full w-2/5 rounded-full bg-indigo-400" />
        ) : (
          <div className="h-full rounded-full bg-indigo-500 transition-all duration-700" style={{ width: `${(processed / total) * 100}%` }} />
        )}
      </div>
      {processed > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-slate-100 pt-3">
          <span className="microlabel mr-1 hidden sm:inline">Sorted so far</span>
          {tally.map(([intent, n]) => (
            <span key={intent} className="hidden sm:inline-flex items-center gap-1.5 rounded-md bg-white px-1.5 py-0.5 text-xs text-slate-600 ring-1 ring-slate-200 ring-inset">
              {intentLabel(intent)} <span className="font-mono text-slate-800 tabular-nums">{n}</span>
            </span>
          ))}
          <button onClick={onReview} className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:underline">
            Review what's ready <ArrowRight className="size-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}

/** Shown once when drafting of new messages finishes. */
function ReadyBanner({ count, seconds, onReview, onClose }: { count: number; seconds: number; onReview: () => void; onClose: () => void }) {
  return (
    <div className="animate-row flex flex-wrap items-center gap-3 rounded-lg border border-emerald-200 bg-emerald-50/80 px-4 py-2.5 text-sm text-emerald-900">
      <CheckCircle2 className="size-4 text-emerald-600" />
      <span className="flex-1">
        <span className="font-medium">{count} new message{count === 1 ? " is" : "s are"} in the queue</span>
        {seconds > 0 && <span className="text-emerald-800/80"> · drafted in {formatDuration(seconds)}</span>}
      </span>
      <button onClick={onReview} className="rounded-lg bg-white px-2.5 py-1 text-xs font-medium text-emerald-800 ring-1 ring-emerald-200 hover:bg-emerald-50">
        Review now
      </button>
      <button onClick={onClose} className="rounded p-1 text-emerald-700/70 hover:bg-emerald-100 hover:text-emerald-900" aria-label="Dismiss">
        <X className="size-4" />
      </button>
    </div>
  );
}

function SignIn() {
  return (
    <div className="grid h-full place-items-center p-4">
      <div className="card hero-grid corners flex w-full max-w-sm flex-col items-center gap-5 p-8 text-center">
        <LogoMark size={44} />
        <div>
          <p className="microlabel !text-indigo-500/80">Recruiting triage</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">Inbox Helper</h1>
          <p className="mt-1 text-sm text-slate-500">Sign in with the Google account your team added to the reviewer list.</p>
        </div>
        <a
          href={api.loginUrl}
          className="flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 text-sm font-medium text-on-accent shadow-sm shadow-indigo-600/20 hover:bg-indigo-500"
        >
          <LogIn className="size-4" /> Sign in with Google
        </a>
        <p className="text-xs text-slate-400">Your account is recorded on every approval, edit and rejection.</p>
      </div>
    </div>
  );
}
