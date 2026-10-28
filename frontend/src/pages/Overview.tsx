import { useEffect, useMemo, useRef, useState, type DragEvent, type ReactNode } from "react";
import {
  AlertCircle, AlertTriangle, ArrowRight, Check, CheckCircle2, FileText, FileUp, Info, Loader2, Mail, MailX, Play,
  RefreshCw, Reply, ShieldAlert, X, XCircle,
} from "lucide-react";
import { api } from "../api";
import type { StatusFilter } from "../components/MessageList";
import { NO_REPLY, type Group } from "../components/Sidebar";
import { formatDuration, formatWhen, intentLabel } from "../lib/labels";
import { useNow } from "../lib/useNow";
import type { FetchProgress, GmailStatus, Item } from "../types";
import { Button, PageHeader, cx } from "../components/ui";

/** Where a tile or bar leads in the review queue. */
export type QueueView = { group: Group; status: StatusFilter };

/** The first page: bring messages in, and see how many wait in each section of the one review queue. */
export function Overview({ items, intents, drafting, gmail, onGmailChange, onStarted, onOpen }: {
  items: Item[];
  intents: string[];
  drafting: ReactNode;
  gmail: GmailStatus | null;
  onGmailChange: () => void;
  onStarted: (summary: string) => void;
  onOpen: (view: QueueView) => void;
}) {
  return (
    <div className="pane h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-5 p-4 sm:p-6">
        <PageHeader
          eyebrow="Candidate inbox"
          title="Overview"
          subtitle="Bring in candidate emails. The AI sorts them by what each person wants and drafts a reply; you approve every one. Nothing is sent automatically."
        />
        <Sources gmail={gmail} onGmailChange={onGmailChange} onStarted={onStarted} />
        {drafting}
        {items.length ? <Sections items={items} intents={intents} onOpen={onOpen} /> : <EmptyQueue />}
      </div>
    </div>
  );
}

// ---- where messages come from ------------------------------------------------------------------------------
function Sources({ gmail, onGmailChange, onStarted }: {
  gmail: GmailStatus | null;
  onGmailChange: () => void;
  onStarted: (summary: string) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState<"fetch" | "upload" | "sample" | "disconnect" | null>(null);
  const [note, setNote] = useState<{ text: string; tone: "info" | "error" } | null>(null);
  const [progress, setProgress] = useState<FetchProgress | null>(null);
  const [fetchStart, setFetchStart] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  // while a fetch runs, poll its progress (the fetch request itself only answers at the end)
  useEffect(() => {
    if (busy !== "fetch") return setProgress(null);
    let live = true;
    const t = window.setInterval(() => {
      api.gmailStatus().then((s) => live && s.fetch && setProgress(s.fetch)).catch(() => undefined);
    }, 600);
    return () => {
      live = false;
      window.clearInterval(t);
    };
  }, [busy]);

  const fetchNew = async () => {
    setBusy("fetch");
    setFetchStart(Date.now());
    setNote(null);
    try {
      const r = await api.gmailFetch();
      const skipped = r.errors.length ? ` ${r.errors.length} could not be used: ${r.errors.map((e) => e.error).join("; ")}` : "";
      if (r.id != null) onStarted(`${r.imported} new email${r.imported === 1 ? "" : "s"} added to the queue`);
      else setNote({ text: `No new emails since the last fetch.${skipped}`, tone: "info" });
    } catch (e) {
      setNote({ text: (e as Error).message, tone: "error" });
    } finally {
      setBusy(null);
      onGmailChange(); // last fetched time, or a connection that stopped working
    }
  };

  const startFile = async (kind: "upload" | "sample") => {
    setBusy(kind);
    setNote(null);
    try {
      const r = kind === "sample" ? await api.startSample() : await api.upload(file!);
      setFile(null);
      onStarted(`${r.added} message${r.added === 1 ? "" : "s"} added to the queue` +
        (r.skipped ? ` · ${r.skipped} already in it were skipped` : ""));
      if (r.errors.length) {
        const rows = r.errors.slice(0, 3).map((e) => `row ${e.row}: ${e.error}`).join("; ");
        setNote({ text: `${r.errors.length} row${r.errors.length === 1 ? "" : "s"} could not be used (${rows}${r.errors.length > 3 ? "; …" : ""}).`, tone: "info" });
      }
    } catch (e) {
      setNote({ text: (e as Error).message, tone: "error" });
    } finally {
      setBusy(null);
    }
  };

  const disconnect = async () => {
    setBusy("disconnect");
    await api.gmailDisconnect();
    setNote(null);
    onGmailChange();
    setBusy(null);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files?.[0];
    if (f) setFile(f);
  };

  const gmailOn = !!gmail?.enabled;
  const gmailReady = gmailOn && gmail!.connected && !gmail!.error;
  const browse = (
    <button className="font-medium text-indigo-600 underline-offset-4 hover:underline" onClick={() => input.current?.click()}>
      browse files
    </button>
  );
  const sample = (
    <button className="font-medium text-indigo-600 underline-offset-4 hover:underline disabled:opacity-50" disabled={!!busy} onClick={() => startFile("sample")}>
      use the sample inbox
    </button>
  );

  return (
    <div>
      <div
        className={cx(
          "card hero-grid corners flex flex-col items-center gap-5 overflow-hidden px-6 py-10 text-center transition-colors",
          dragging && "corners-active border-indigo-300 bg-indigo-50/40",
        )}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        {dragging ? (
          <SourceHead icon={<FileUp className="size-6" />} title="Release to add the file" />
        ) : file ? (
          <>
            <SourceHead icon={<FileText className="size-6" />} title="1 file ready" sub="Nothing is processed until you start." />
            <div className="flex w-full max-w-md items-center gap-3 rounded-lg border border-slate-200 bg-white/80 py-2 pr-1.5 pl-3 text-left">
              <FileText className="size-4 shrink-0 text-indigo-500" />
              <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-800">{file.name}</span>
              <span className="font-mono text-xs text-slate-400">{(file.size / 1024).toFixed(1)} KB</span>
              <button onClick={() => setFile(null)} disabled={!!busy} className="grid size-8 place-items-center rounded-md text-slate-400 hover:bg-rose-50 hover:text-rose-600" title="Remove">
                <X className="size-4" />
              </button>
            </div>
            <div className="flex flex-wrap justify-center gap-2">
              <Button variant="primary" icon={<Play className="size-4" />} loading={busy === "upload"} disabled={!!busy} onClick={() => startFile("upload")}>
                Start triage
              </Button>
              <Button variant="ghost" disabled={!!busy} onClick={() => input.current?.click()}>
                Choose another
              </Button>
            </div>
          </>
        ) : gmailOn ? (
          <>
            <SourceHead
              icon={<Mail className="size-6" />}
              title={gmailReady ? "Fetch new emails" : gmail!.connected ? "Reconnect Gmail" : "Connect your recruiting inbox"}
              sub={
                gmailReady
                  ? `From ${gmail!.account} · ${gmail!.last_fetch_at ? `last fetched ${formatWhen(gmail!.last_fetch_at)}` : "not fetched yet"}`
                  : gmail!.error ?? `Sign in to Google as ${gmail!.account}. New emails are read; approved replies become Gmail drafts.`
              }
            />
            {gmailReady ? (
              busy === "fetch" ? (
                <FetchSteps progress={progress} startedAt={fetchStart} />
              ) : (
                <Button variant="primary" icon={<RefreshCw className="size-4" />} disabled={!!busy} onClick={fetchNew}>
                  Fetch new emails
                </Button>
              )
            ) : (
              <a href={api.gmailConnectUrl} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 text-sm font-medium text-on-accent shadow-sm shadow-indigo-600/20 hover:bg-indigo-500">
                <Mail className="size-4" /> {gmail!.connected ? "Reconnect Gmail" : "Connect Gmail"}
              </a>
            )}
            {busy !== "fetch" && (
              <>
                <div className="flex w-full max-w-md items-center gap-3 text-slate-400">
                  <span className="h-px flex-1 bg-gradient-to-r from-transparent to-slate-300" />
                  <span className="microlabel">or</span>
                  <span className="h-px flex-1 bg-gradient-to-l from-transparent to-slate-300" />
                </div>
                <p className="text-sm text-slate-500">
                  Drop a CSV or JSON file here, {browse}, or {sample}.
                </p>
              </>
            )}
          </>
        ) : (
          <>
            <SourceHead icon={<FileUp className="size-6" />} title="Drop candidate messages here" />
            <p className="-mt-3 text-sm text-slate-500">
              or {browse}. A CSV or JSON file with <code className="font-mono text-[13px]">message_id</code> and{" "}
              <code className="font-mono text-[13px]">body</code>, up to 2 MB. Nothing is processed until you start. Or {sample}.
            </p>
          </>
        )}

        {busy === "sample" && <Loader2 className="size-5 animate-spin text-indigo-500" />}
        {note && (
          <p className={cx("flex max-w-lg items-start gap-2 text-left text-sm", note.tone === "error" ? "text-rose-700" : "text-slate-600")}>
            {note.tone === "error" && <AlertCircle className="mt-0.5 size-4 shrink-0" />}
            {note.text}
          </p>
        )}
        <input ref={input} type="file" accept=".csv,.json" className="hidden" onChange={(e) => {
          setFile(e.target.files?.[0] ?? null);
          e.target.value = "";
        }} />
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 px-1 text-xs text-slate-400">
        <span className="flex items-center gap-1.5">
          <Info className="size-3.5" /> Messages go to free-tier AI models that may keep inputs. Use synthetic data only.
        </span>
        {gmail?.connected && (
          <button onClick={disconnect} disabled={!!busy} className="ml-auto underline-offset-2 hover:text-slate-700 hover:underline">
            Disconnect Gmail
          </button>
        )}
      </div>
    </div>
  );
}

function SourceHead({ icon, title, sub }: { icon: React.ReactNode; title: string; sub?: string }) {
  return (
    <>
      <div className="grid size-14 place-items-center rounded-2xl border border-indigo-200 bg-indigo-50/80 text-indigo-600">{icon}</div>
      <div className="-mt-1">
        <p className="text-lg font-medium text-slate-900">{title}</p>
        {sub && <p className="mt-1 max-w-xl text-sm text-slate-500">{sub}</p>}
      </div>
    </>
  );
}

const FETCH_STEPS: { stage: FetchProgress["stage"]; label: string }[] = [
  { stage: "searching", label: "Search the inbox" },
  { stage: "downloading", label: "Download new emails" },
  { stage: "queueing", label: "Hand them to the AI" },
];

/** Live steps of a running fetch, from the server's progress (null until the first poll answers). */
function FetchSteps({ progress, startedAt }: { progress: FetchProgress | null; startedAt: number }) {
  const now = useNow(true);
  const stage = progress?.stage ?? "searching";
  const current = FETCH_STEPS.findIndex((s) => s.stage === stage);
  const found = progress?.found ?? 0;
  const downloaded = progress?.downloaded ?? 0;

  return (
    <div className="w-full max-w-md rounded-lg border border-slate-200 bg-white/90 p-4 text-left" aria-live="polite">
      <div className="mb-3 flex items-center justify-between">
        <span className="microlabel !text-indigo-500">Fetching</span>
        <span className="font-mono text-xs text-slate-400 tabular-nums">{formatDuration((now - startedAt) / 1000)}</span>
      </div>
      <ol className="space-y-2.5">
        {FETCH_STEPS.map((step, i) => {
          const done = i < current;
          const active = i === current;
          return (
            <li key={step.stage} className="flex items-center gap-2.5 text-sm">
              <span
                className={cx(
                  "grid size-5 shrink-0 place-items-center rounded-full",
                  done ? "bg-emerald-500 text-on-accent" : active ? "bg-indigo-50 text-indigo-600 ring-1 ring-indigo-200" : "ring-1 ring-slate-200",
                )}
              >
                {done ? <Check className="size-3" strokeWidth={3} /> : active ? <Loader2 className="size-3 animate-spin" /> : null}
              </span>
              <span className={cx("flex-1", done ? "text-slate-500" : active ? "font-medium text-slate-800" : "text-slate-400")}>{step.label}</span>
              <span className="font-mono text-xs text-slate-500 tabular-nums">
                {step.stage === "searching" && (done || found > 0) && `${found} new`}
                {step.stage === "downloading" && (active || done) && `${downloaded}/${found}`}
              </span>
            </li>
          );
        })}
      </ol>
      <div className="mt-3.5 h-1 overflow-hidden rounded-full bg-slate-100">
        {stage === "downloading" && found > 0 ? (
          <div className="h-full rounded-full bg-indigo-500 transition-all duration-300" style={{ width: `${(downloaded / found) * 100}%` }} />
        ) : (
          <div className={cx("h-full rounded-full", stage === "queueing" ? "w-full bg-indigo-500" : "animate-indeterminate w-2/5 bg-indigo-400")} />
        )}
      </div>
    </div>
  );
}

// ---- how many wait where -----------------------------------------------------------------------------------
function Sections({ items, intents, onOpen }: { items: Item[]; intents: string[]; onOpen: (view: QueueView) => void }) {
  const c = useMemo(() => {
    const pending = items.filter((i) => i.review_status === "pending");
    const byIntent = new Map<string, number>();
    for (const i of pending) byIntent.set(i.intent, (byIntent.get(i.intent) ?? 0) + 1);
    return {
      pending: pending.length,
      attention: pending.filter((i) => i.priority_review).length,
      noReply: byIntent.get(NO_REPLY) ?? 0,
      quarantined: byIntent.get("manipulation_attempt") ?? 0,
      approved: items.filter((i) => i.review_status === "approved").length,
      closed: items.filter((i) => i.review_status === "rejected").length,
      byIntent,
    };
  }, [items]);
  const toReply = c.pending - c.noReply - c.quarantined;
  const bars = intents.map((i) => ({ intent: i, n: c.byIntent.get(i) ?? 0 })).filter((b) => b.n > 0).sort((a, b) => b.n - a.n);
  const max = Math.max(1, ...bars.map((b) => b.n));

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <div className="space-y-4">
        <div className="card p-5">
          <p className="microlabel">Waiting for you</p>
          <p className="mt-2 font-mono text-[44px] leading-none font-semibold tracking-tight text-slate-950 tabular-nums">{c.pending}</p>
          <p className="mt-2 text-sm text-slate-500">
            {c.pending === 0
              ? "Everything is reviewed."
              : c.attention > 0
                ? `Start with the ${c.attention} that need${c.attention === 1 ? "s" : ""} attention.`
                : "Nothing urgent. Work through them in order."}
          </p>
          {c.pending > 0 && (
            <Button
              variant="primary"
              className="mt-4"
              onClick={() => onOpen({ group: c.attention > 0 ? "attention" : "all", status: "pending" })}
            >
              Start reviewing <ArrowRight className="size-4" />
            </Button>
          )}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Tile icon={<AlertTriangle className="size-4 text-rose-500" />} label="Need attention" value={c.attention}
            onClick={() => onOpen({ group: "attention", status: "pending" })} />
          <Tile icon={<Reply className="size-4 text-indigo-500" />} label="To reply" value={toReply}
            onClick={() => onOpen({ group: "all", status: "pending" })} />
          <Tile icon={<MailX className="size-4 text-slate-400" />} label="No reply needed" value={c.noReply}
            hint="AI suggests closing" onClick={() => onOpen({ group: NO_REPLY, status: "pending" })} />
          <Tile icon={<ShieldAlert className="size-4 text-red-600" />} label="Quarantined" value={c.quarantined}
            onClick={() => onOpen({ group: "manipulation_attempt", status: "pending" })} />
          <Tile icon={<CheckCircle2 className="size-4 text-emerald-500" />} label="Approved" value={c.approved}
            onClick={() => onOpen({ group: "all", status: "approved" })} />
          <Tile icon={<XCircle className="size-4 text-slate-400" />} label="Closed" value={c.closed}
            hint="Rejected, or closed without a reply" onClick={() => onOpen({ group: "all", status: "rejected" })} />
        </div>
      </div>

      <div className="card p-5">
        <div className="flex items-baseline justify-between">
          <p className="microlabel">To reply, by what they want</p>
          <span className="font-mono text-xs text-slate-400 tabular-nums">{toReply} waiting</span>
        </div>
        {bars.length === 0 ? (
          <p className="py-10 text-center text-sm text-slate-400">No replies waiting.</p>
        ) : (
          <ul className="mt-4 space-y-1">
            {bars.map((b) => (
              <li key={b.intent}>
                <button
                  onClick={() => onOpen({ group: b.intent, status: "pending" })}
                  title={`${b.n} ${intentLabel(b.intent)} message${b.n === 1 ? "" : "s"} waiting`}
                  className="group grid w-full grid-cols-[9.5rem_1fr_2.5rem] items-center gap-3 rounded-lg px-2 py-2 text-left hover:bg-slate-50"
                >
                  <span className="truncate text-sm text-slate-700 group-hover:text-slate-950">{intentLabel(b.intent)}</span>
                  <span className="h-2 rounded-full bg-slate-100">
                    <span className="block h-full rounded-full bg-indigo-400 transition-all group-hover:bg-indigo-500" style={{ width: `${(b.n / max) * 100}%` }} />
                  </span>
                  <span className="text-right font-mono text-sm text-slate-700 tabular-nums">{b.n}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function Tile({ icon, label, value, hint, onClick }: { icon: ReactNode; label: string; value: number; hint?: string; onClick: () => void }) {
  return (
    <button onClick={onClick} className="card group flex flex-col p-4 text-left transition-colors hover:border-indigo-200">
      <div className="flex items-center justify-between">
        <span className="microlabel">{label}</span>
        <span className={cx("transition-opacity", value === 0 && "opacity-40")}>{icon}</span>
      </div>
      <p className={cx("mt-2 font-mono text-[26px] leading-8 font-semibold tracking-tight tabular-nums", value ? "text-slate-950" : "text-slate-300")}>{value}</p>
      {hint && <p className="mt-0.5 truncate text-xs text-slate-400">{hint}</p>}
    </button>
  );
}

function EmptyQueue() {
  return (
    <div className="card flex flex-col items-center gap-2 py-14 text-center">
      <EnvelopeArt />
      <p className="mt-2 font-medium text-slate-700">The queue is empty</p>
      <p className="max-w-sm text-sm leading-relaxed text-slate-500">
        Fetch from Gmail or drop a file above. New messages are sorted and drafted, then counted here by section.
      </p>
    </div>
  );
}

/** Dashed envelope with dimension lines: the empty-state drawing. */
function EnvelopeArt() {
  return (
    <svg width="104" height="72" viewBox="0 0 120 84" fill="none" className="opacity-80" aria-hidden>
      <g stroke="rgb(79 70 229)" strokeOpacity="0.55" strokeWidth="1.1" strokeDasharray="4 3">
        <rect x="32" y="14" width="56" height="38" rx="2" />
        <path d="M32 16 L60 36 L88 16" />
      </g>
      <g stroke="#94a3b8" strokeWidth="0.8">
        <path d="M32 62 H88 M32 58 v8 M88 58 v8" />
        <path d="M98 14 V52 M94 14 h8 M94 52 h8" />
      </g>
      <g fill="#94a3b8" fontFamily="JetBrains Mono, monospace" fontSize="6.5">
        <text x="52" y="73">56.00</text>
        <text x="103" y="35">38.0</text>
      </g>
    </svg>
  );
}
