import { useEffect, useState } from "react";
import { PenLine, RotateCcw, X } from "lucide-react";
import { api } from "../api";
import type { Signature } from "../types";
import { Button } from "./ui";

const SAMPLE_BODY = "Thanks for checking in. The recruiter will look at your application and follow up this week.";

/** The signed-in reviewer's greeting and sign-off. Drafts are shown with them; the AI only writes the body. */
export function SignatureDialog({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => void }) {
  const [current, setCurrent] = useState<Signature | null>(null);
  const [greeting, setGreeting] = useState("");
  const [signOff, setSignOff] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    api.signature().then((s) => {
      setCurrent(s);
      setGreeting(s.greeting ?? "");
      setSignOff(s.sign_off ?? "");
    });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const save = async (values: { greeting: string; sign_off: string }) => {
    setBusy(true);
    setError(null);
    try {
      await api.saveSignature(values);
      onSaved();
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const defaults = current?.defaults;
  const shownGreeting = (greeting.trim() || defaults?.greeting || "").replace("{first_name}", "Rabia").replace("{name}", "Rabia Aslam");
  const shownSignOff = signOff.trim() || defaults?.sign_off || "";

  return (
    <div data-overlay className="fixed inset-0 z-50 grid place-items-center bg-slate-900/30 p-4 backdrop-blur-sm" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="signature-title"
        onMouseDown={(e) => e.stopPropagation()}
        className="card max-h-[92vh] w-full max-w-lg overflow-y-auto p-6 shadow-pop"
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <p className="microlabel !text-indigo-500/80">Your settings</p>
            <h2 id="signature-title" className="mt-1 flex items-center gap-2 text-lg font-semibold tracking-tight">
              <PenLine className="size-5 text-slate-400" /> Reply signature
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              The AI writes only the body of each reply. Your greeting and sign-off are added around it, the same way every
              time. Leave a box empty to use the team default.
            </p>
          </div>
          <button onClick={onClose} aria-label="Close" className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600">
            <X className="size-5" />
          </button>
        </div>

        <label className="block">
          <span className="text-sm font-medium text-slate-700">Greeting</span>
          <input
            value={greeting}
            onChange={(e) => setGreeting(e.target.value)}
            placeholder={defaults?.greeting}
            className="mt-1 h-9 w-full rounded-lg bg-white px-3 text-sm ring-1 ring-slate-200 ring-inset placeholder:text-slate-400 focus:ring-2 focus:ring-indigo-500 focus:outline-none"
          />
          <span className="mt-1 block text-xs text-slate-500">
            <code className="font-mono">{"{first_name}"}</code> becomes the sender's first name. Senders without a person's
            name (a team, a company) get "Hello,".
          </span>
        </label>

        <label className="mt-4 block">
          <span className="text-sm font-medium text-slate-700">Sign-off</span>
          <textarea
            value={signOff}
            onChange={(e) => setSignOff(e.target.value)}
            placeholder={defaults?.sign_off}
            rows={3}
            className="mt-1 w-full resize-y rounded-lg bg-white px-3 py-2 text-sm ring-1 ring-slate-200 ring-inset placeholder:text-slate-400 focus:ring-2 focus:ring-indigo-500 focus:outline-none"
          />
          <span className="mt-1 block text-xs text-slate-500">Up to 6 lines, for example a closing line and your name.</span>
        </label>

        <div className="mt-5">
          <p className="microlabel">Preview</p>
          <p className="mt-2 rounded-lg bg-slate-50 px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap text-slate-700 ring-1 ring-slate-200">
            {`${shownGreeting}\n\n${SAMPLE_BODY}\n\n${shownSignOff}`}
          </p>
        </div>

        {error && <p className="mt-3 text-sm text-rose-700">{error}</p>}

        <div className="mt-5 flex flex-col-reverse gap-2 border-t border-slate-100 pt-4 sm:flex-row sm:items-center">
          <Button
            variant="ghost"
            icon={<RotateCcw className="size-4" />}
            disabled={busy || (!current?.greeting && !current?.sign_off)}
            onClick={() => save({ greeting: "", sign_off: "" })}
          >
            Use the default
          </Button>
          <span className="flex-1" />
          <Button variant="secondary" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={() => save({ greeting, sign_off: signOff })}>
            Save
          </Button>
        </div>
        <p className="mt-3 text-xs text-slate-500">
          Drafts waiting for review switch to the new signature. Replies you already edited or approved keep what they say. Replies in another language (Spanish, Urdu, ...) get a greeting and sign-off in that language instead.
        </p>
      </div>
    </div>
  );
}
