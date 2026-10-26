import { useState } from "react";
import { Ban, X } from "lucide-react";
import { formatWhen } from "../lib/labels";
import type { BlockedSender } from "../types";
import { Button } from "./ui";

export function BlocklistDialog({ open, blocked, reviewer, onClose, onUnblock }: {
  open: boolean;
  blocked: BlockedSender[];
  reviewer: string;
  onClose: () => void;
  onUnblock: (email: string) => Promise<void>;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-slate-900/30 p-4 backdrop-blur-sm" onMouseDown={onClose}>
      <div onMouseDown={(e) => e.stopPropagation()} className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl ring-1 ring-slate-200">
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
              <Ban className="size-5 text-zinc-700" /> Blocked senders
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              Messages from these addresses are never sent to the AI and never answered. Email addresses can be forged, so
              check before blocking.
            </p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600" aria-label="Close">
            <X className="size-5" />
          </button>
        </div>

        {blocked.length === 0 ? (
          <p className="rounded-xl bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">No one is blocked.</p>
        ) : (
          <ul className="divide-y divide-slate-100 rounded-xl ring-1 ring-slate-200">
            {blocked.map((b) => (
              <li key={b.email} className="flex items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-slate-900">{b.email}</div>
                  <div className="truncate text-xs text-slate-500">
                    {b.reason ? `${b.reason} · ` : ""}by {b.blocked_by} · {formatWhen(b.blocked_at)}
                  </div>
                </div>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={!reviewer.trim() || (busy !== null && busy !== b.email)}
                  loading={busy === b.email}
                  title={reviewer.trim() ? "Process this sender's future messages again" : "Enter your name at the top first"}
                  onClick={async () => {
                    setBusy(b.email);
                    try {
                      await onUnblock(b.email);
                    } finally {
                      setBusy(null);
                    }
                  }}
                >
                  Unblock
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
