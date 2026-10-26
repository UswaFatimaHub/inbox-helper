import { useRef, useState, type DragEvent } from "react";
import { AlertCircle, FileUp, Inbox, Info, X } from "lucide-react";
import { api } from "../api";
import { Button, cx } from "./ui";

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
        Messages are sent to free-tier AI models (Gemini, OpenRouter) which may retain inputs. Use synthetic data only.
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
