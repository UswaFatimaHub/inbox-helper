import { useEffect, useRef, useState, type DragEvent } from "react";
import { AlertCircle, Check, FileUp, Inbox, Info, Loader2, Mail, RefreshCw, X } from "lucide-react";
import { api } from "../api";
import { formatDuration, formatWhen } from "../lib/labels";
import { useNow } from "../lib/useNow";
import type { FetchProgress, GmailStatus } from "../types";
import { Button, cx } from "./ui";

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
    <div className="mt-3 rounded-lg bg-white p-3 ring-1 ring-slate-200" aria-live="polite">
      <div className="mb-2.5 flex items-center justify-between text-xs">
        <span className="font-medium text-slate-700">Fetching new emails…</span>
        <span className="text-slate-400 tabular-nums">{formatDuration((now - startedAt) / 1000)}</span>
      </div>
      <ol className="space-y-2">
        {FETCH_STEPS.map((step, i) => {
          const done = i < current;
          const active = i === current;
          return (
            <li key={step.stage} className="flex items-center gap-2.5 text-sm">
              <span
                className={cx(
                  "grid size-5 shrink-0 place-items-center rounded-full",
                  done ? "bg-emerald-500 text-white" : active ? "bg-indigo-50 text-indigo-600 ring-1 ring-indigo-200" : "ring-1 ring-slate-200",
                )}
              >
                {done ? <Check className="size-3" strokeWidth={3} /> : active ? <Loader2 className="size-3 animate-spin" /> : null}
              </span>
              <span className={cx("flex-1", done ? "text-slate-500" : active ? "font-medium text-slate-800" : "text-slate-400")}>{step.label}</span>
              <span className="text-xs text-slate-500 tabular-nums">
                {step.stage === "searching" && (done || found > 0) && `${found} new`}
                {step.stage === "downloading" && (active || done) && `${downloaded} / ${found}`}
              </span>
            </li>
          );
        })}
      </ol>
      <div className="mt-3 h-1 overflow-hidden rounded-full bg-slate-100">
        {stage === "downloading" && found > 0 ? (
          <div className="h-full rounded-full bg-indigo-500 transition-all duration-300" style={{ width: `${(downloaded / found) * 100}%` }} />
        ) : (
          <div className={cx("h-full w-2/5 rounded-full", stage === "queueing" ? "w-full bg-indigo-500" : "animate-indeterminate bg-indigo-400")} />
        )}
      </div>
    </div>
  );
}

/** Fetch from the connected Gmail inbox, or connect it. Hidden entirely when the server has no Gmail settings. */
function GmailSource({ onStarted }: { onStarted: (runId: number) => void }) {
  const [status, setStatus] = useState<GmailStatus | null>(null);
  const [busy, setBusy] = useState<"fetch" | "disconnect" | null>(null);
  const [note, setNote] = useState<{ text: string; tone: "info" | "error" } | null>(null);
  const [progress, setProgress] = useState<FetchProgress | null>(null);
  const [fetchStart, setFetchStart] = useState(0);

  const load = () => api.gmailStatus().then(setStatus).catch(() => setStatus(null));
  useEffect(() => {
    load();
  }, []);

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

  if (!status) return null;
  if (!status.enabled) {
    return (
      <p className="mb-4 text-xs text-slate-400">
        Gmail import is off. To turn it on, set {status.missing.join(", ")} on the server.
      </p>
    );
  }

  const fetchNew = async () => {
    setBusy("fetch");
    setFetchStart(Date.now());
    setNote(null);
    try {
      const r = await api.gmailFetch();
      const skipped = r.errors.length ? ` ${r.errors.length} could not be used: ${r.errors.map((e) => e.error).join("; ")}` : "";
      if (r.id != null) onStarted(r.id);
      else setNote({ text: `No new emails in ${status.account}.${skipped}`, tone: "info" });
    } catch (e) {
      setNote({ text: (e as Error).message, tone: "error" });
      load(); // the connection may have stopped working
    } finally {
      setBusy(null);
    }
  };

  const disconnect = async () => {
    setBusy("disconnect");
    await api.gmailDisconnect();
    setNote(null);
    await load();
    setBusy(null);
  };

  const working = status.connected && !status.error;
  return (
    <div className="mb-4 rounded-xl bg-slate-50 p-3 ring-1 ring-slate-200">
      <div className="flex flex-wrap items-center gap-3">
        <div className="grid size-9 shrink-0 place-items-center rounded-full bg-white text-rose-500 ring-1 ring-slate-200">
          <Mail className="size-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-slate-800">{status.account}</div>
          <div className="text-xs text-slate-500">
            {!status.connected
              ? "Gmail inbox · not connected"
              : status.error
                ? "Connection stopped working"
                : status.last_fetch_at
                  ? `Last fetched ${formatWhen(status.last_fetch_at)}`
                  : "Connected · not fetched yet"}
          </div>
        </div>
        {working ? (
          <Button variant="primary" size="sm" icon={<RefreshCw className="size-3.5" />} loading={busy === "fetch"} disabled={!!busy} onClick={fetchNew}>
            Fetch new emails
          </Button>
        ) : (
          <a
            href={api.gmailConnectUrl}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-indigo-600 px-3 text-sm font-medium text-white shadow-sm hover:bg-indigo-500"
          >
            <Mail className="size-3.5" /> {status.connected ? "Reconnect Gmail" : "Connect Gmail"}
          </a>
        )}
      </div>
      {busy === "fetch" && <FetchSteps progress={progress} startedAt={fetchStart} />}
      {status.error && <p className="mt-2 text-xs text-amber-700">{status.error}</p>}
      {note && <p className={cx("mt-2 text-xs", note.tone === "error" ? "text-rose-700" : "text-slate-600")}>{note.text}</p>}
      <p className="mt-2 text-xs text-slate-500">
        Approved replies become Gmail drafts in the original thread; you send them from Gmail.
        {status.connected && (
          <button onClick={disconnect} disabled={!!busy} className="ml-1 text-slate-400 underline-offset-2 hover:text-slate-700 hover:underline">
            Disconnect
          </button>
        )}
      </p>
    </div>
  );
}

export function NewRunPanel({ onStarted, onClose, inline }: {
  onStarted: (runId: number) => void;
  onClose?: () => void;
  inline?: boolean;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState<"upload" | "sample" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const start = async (kind: "upload" | "sample") => {
    setBusy(kind);
    setError(null);
    try {
      const { id } = kind === "sample" ? await api.startSample() : await api.upload(file!);
      onStarted(id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files?.[0];
    if (f) setFile(f);
  };

  return (
    <div className={cx("w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl ring-1 ring-slate-200", inline && "shadow-sm")}>
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Triage an inbox</h2>
          <p className="mt-1 text-sm text-slate-500">
            Upload candidate messages. The AI groups them by what each person wants and drafts a reply for you to review.
          </p>
        </div>
        {onClose && (
          <button onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600" aria-label="Close">
            <X className="size-5" />
          </button>
        )}
      </div>

      <GmailSource onStarted={onStarted} />

      <button
        type="button"
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cx(
          "flex w-full flex-col items-center gap-2 rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors",
          dragging ? "border-indigo-400 bg-indigo-50/60" : "border-slate-200 hover:border-indigo-300 hover:bg-slate-50",
        )}
      >
        <div className="grid size-11 place-items-center rounded-full bg-indigo-50 text-indigo-600">
          <FileUp className="size-5" />
        </div>
        {file ? (
          <>
            <div className="text-sm font-medium text-slate-800">{file.name}</div>
            <div className="text-xs text-slate-500">{(file.size / 1024).toFixed(1)} KB · click to choose another</div>
          </>
        ) : (
          <>
            <div className="text-sm font-medium text-slate-800">Drop a CSV or JSON file, or click to browse</div>
            <div className="text-xs text-slate-500">Needs <code>message_id</code> and <code>body</code> columns · max 2 MB</div>
          </>
        )}
      </button>
      <input
        ref={input}
        type="file"
        accept=".csv,.json"
        className="hidden"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
      />

      {error && (
        <div className="mt-4 flex gap-2 rounded-lg bg-rose-50 px-3 py-2.5 text-sm text-rose-700 ring-1 ring-rose-200">
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-between">
        <Button variant="ghost" icon={<Inbox className="size-4" />} loading={busy === "sample"} disabled={!!busy} onClick={() => start("sample")}>
          Use sample inbox
        </Button>
        <Button variant="primary" disabled={!file || !!busy} loading={busy === "upload"} onClick={() => start("upload")}>
          Start triage
        </Button>
      </div>

      <p className="mt-5 flex gap-2 border-t border-slate-100 pt-4 text-xs leading-relaxed text-slate-500">
        <Info className="mt-0.5 size-3.5 shrink-0" />
        Messages, including fetched emails, are sent to free-tier AI models (Gemini, OpenRouter) which may retain inputs.
        Use synthetic data only.
      </p>
    </div>
  );
}

export function NewRunDialog({ open, onClose, onStarted }: { open: boolean; onClose: () => void; onStarted: (id: number) => void }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-slate-900/30 p-4 backdrop-blur-sm" onMouseDown={onClose}>
      <div onMouseDown={(e) => e.stopPropagation()} className="w-full max-w-lg">
        <NewRunPanel onClose={onClose} onStarted={onStarted} />
      </div>
    </div>
  );
}
