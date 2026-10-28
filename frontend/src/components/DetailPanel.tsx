import { useState } from "react";
import {
  AlertTriangle, ArrowLeft, Ban, Check, ChevronDown, ChevronUp, Copy, History, Mail, RefreshCw, RotateCcw, Save,
  ShieldAlert, Sparkles, Undo2, X,
} from "lucide-react";
import { flagSeverity, formatWhen, initials, shortModel } from "../lib/labels";
import type { Item, Meta } from "../types";
import { Button, Card, FlagChip, IntentChip, StatusPill, cx } from "./ui";

export type Action = "save" | "approve" | "reject" | "reopen" | "regenerate" | "block" | "unblock" | "draft";

const SEVERITY_ORDER = { high: 0, attention: 1, info: 2 } as const;

const EVENT_TEXT: Record<string, string> = {
  edited: "edited the reply",
  approved: "approved the reply",
  rejected: "rejected the draft",
  reopened: "reopened for review",
  regenerated: "asked the AI for a new draft",
  blocked: "blocked the sender",
  unblocked: "unblocked the sender",
  quarantined: "quarantined this message and discarded the AI draft",
  drafted: "saved the reply as a Gmail draft",
  draft_deleted: "deleted the Gmail draft",
  draft_failed: "could not update the Gmail draft",
};

const gmailDraftsUrl = (mailbox: string) => `https://mail.google.com/mail/?authuser=${encodeURIComponent(mailbox)}#drafts`;

export function DetailPanel({ item, meta, reviewer, blockedEmails, onAction, onBack, onPrev, onNext, notify }: {
  item: Item;
  meta: Meta | null;
  reviewer: string;
  blockedEmails: Set<string>;
  onAction: (action: Action, payload?: { text?: string; note?: string }) => Promise<void>;
  onBack: () => void;
  onPrev?: () => void;
  onNext?: () => void;
  notify: (msg: string) => void;
}) {
  const saved = item.final_reply ?? item.draft_reply;
  const [text, setText] = useState(saved);
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<Action | null>(null);
  const [writeAnyway, setWriteAnyway] = useState(false);
  const [blockReason, setBlockReason] = useState("Tried to manipulate the AI (prompt injection)");

  const run = async (action: Action, payload?: { text?: string; note?: string }) => {
    setBusy(action);
    try {
      await onAction(action, payload);
      if (action === "reject") setRejecting(false);
    } finally {
      setBusy(null);
    }
  };

  const pending = item.review_status === "pending";
  const dirty = text.trim() !== saved.trim();
  const editedFromAi = text.trim() !== item.draft_reply.trim();
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  const needName = !reviewer.trim();
  const flags = [...item.flags].sort((a, b) => SEVERITY_ORDER[flagSeverity(a)] - SEVERITY_ORDER[flagSeverity(b)]);
  const high = flags.filter((f) => flagSeverity(f) === "high");
  const quarantined = item.intent === "manipulation_attempt";
  const email = item.candidate_email.trim().toLowerCase();
  const senderBlocked = !!email && blockedEmails.has(email);

  const copy = async (value: string) => {
    await navigator.clipboard.writeText(value);
    notify("Reply copied to clipboard");
  };

  return (
    <div className="pane h-full overflow-y-auto">
      {/* header */}
      <div className="sticky top-0 z-10 border-b border-slate-200/80 bg-canvas/90 px-4 py-3 backdrop-blur lg:px-6">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="rounded-lg p-1.5 text-slate-500 hover:bg-white lg:hidden" aria-label="Back to list">
            <ArrowLeft className="size-5" />
          </button>
          <div className="grid size-10 shrink-0 place-items-center rounded-full bg-gradient-to-br from-slate-100 to-slate-200 text-sm font-semibold text-slate-600 ring-1 ring-slate-200">
            {initials(item.candidate_name || item.candidate_email)}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h2 className="truncate text-base font-semibold tracking-tight">{item.candidate_name || "Unknown sender"}</h2>
              <StatusPill status={item.review_status} />
            </div>
            <div className="flex flex-wrap items-center gap-x-3 text-xs text-slate-500">
              {item.candidate_email && (
                <span className="inline-flex items-center gap-1">
                  <Mail className="size-3" />
                  {item.candidate_email}
                </span>
              )}
              {item.role && <span>{item.role}</span>}
              <span>{formatWhen(item.received_at)}</span>
              <span className="text-slate-400">{item.message_id}</span>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button onClick={onPrev} disabled={!onPrev} title="Previous (K)" className="rounded-lg p-1.5 text-slate-500 hover:bg-white disabled:opacity-30">
              <ChevronUp className="size-5" />
            </button>
            <button onClick={onNext} disabled={!onNext} title="Next (J)" className="rounded-lg p-1.5 text-slate-500 hover:bg-white disabled:opacity-30">
              <ChevronDown className="size-5" />
            </button>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-3xl space-y-4 p-4 lg:p-6">
        {high.length > 0 && pending && !quarantined && (
          <div className="flex gap-3 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-800 ring-1 ring-rose-200">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            <div>
              <div className="font-medium">Check this draft carefully before approving</div>
              <ul className="mt-1 list-disc space-y-0.5 pl-4 text-rose-700">
                {high.map((f) => (
                  <li key={f}>{meta?.flags[f] ?? f}</li>
                ))}
              </ul>
            </div>
          </div>
        )}

        {pending && item.gmail?.draft_error && (
          <div className="flex gap-3 rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-800 ring-1 ring-amber-200">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            <div>{item.gmail.draft_error}</div>
          </div>
        )}

        <Card title="Candidate's message" icon={<Mail className="size-3.5" />}>
          <div className="text-[15px] font-semibold text-slate-900" dir="auto">{item.subject || "(no subject)"}</div>
          <p className="mt-2 text-[15px] leading-relaxed whitespace-pre-wrap text-slate-700" dir="auto">{item.body}</p>
        </Card>

        <Card
          title="AI assessment"
          icon={<Sparkles className="size-3.5" />}
          actions={
            <span className="text-[11px] text-slate-400" title={`${item.lane} · ${item.model}`}>
              {item.model !== "none" ? `${shortModel(item.model)}${item.latency_s ? ` · ${item.latency_s.toFixed(1)}s` : " · cached"}` : "no model"} · prompt {item.prompt_version}
            </span>
          }
        >
          <div className="flex flex-wrap items-center gap-2">
            <IntentChip intent={item.intent} />
            {item.secondary_intent && (
              <>
                <span className="text-xs text-slate-400">and</span>
                <IntentChip intent={item.secondary_intent} muted />
              </>
            )}
            {item.lane === "rules" || item.intent === "manipulation_attempt" ? (
              <span className="ml-auto text-xs text-slate-500">
                {item.flags.includes("injection_pattern") ? "Matched by rule" : "Flagged by the AI"} · no reply drafted
              </span>
            ) : (
            <div className="ml-auto flex items-center gap-2 text-xs text-slate-500" title="How sure the model was about the intent">
              Confidence
              <div className="h-1.5 w-20 overflow-hidden rounded-full bg-slate-100">
                <div
                  className={cx("h-full rounded-full", item.confidence >= 0.8 ? "bg-emerald-500" : item.confidence >= 0.6 ? "bg-amber-400" : "bg-rose-400")}
                  style={{ width: `${Math.round(item.confidence * 100)}%` }}
                />
              </div>
              <span className="w-8 text-right tabular-nums">{Math.round(item.confidence * 100)}%</span>
            </div>
            )}
          </div>
          {item.reason && <p className="mt-3 text-sm text-slate-600">{item.reason}</p>}
          {item.error && <p className="mt-3 rounded-lg bg-slate-50 px-3 py-2 font-mono text-xs text-slate-600">{item.error}</p>}
          {flags.length > 0 && (
            <div className="mt-4 border-t border-slate-100 pt-4">
              <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-slate-500">
                <AlertTriangle className="size-3.5" />
                {flags.length} {flags.length === 1 ? "flag" : "flags"}: why this message needs a closer look
              </div>
              <ul className="space-y-2">
                {flags.map((f) => (
                  <li key={f} className="flex items-start gap-3 text-sm">
                    <FlagChip flag={f} />
                    <span className="text-slate-500">{meta?.flags[f]}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>

        {pending && quarantined && (
          <section className="rounded-2xl bg-white ring-1 ring-red-200 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
            <header className="flex items-center gap-2 rounded-t-2xl border-b border-red-100 bg-red-50/70 px-5 py-3 text-[13px] font-semibold tracking-wide text-red-700 uppercase">
              <ShieldAlert className="size-4" /> Quarantined · no reply drafted
            </header>
            <div className="space-y-4 px-5 py-4 text-sm text-slate-600">
              <p>
                {item.lane === "rules"
                  ? "This message contains a known prompt-injection phrase, so it was never sent to the AI."
                  : item.flags.includes("injection_pattern")
                    ? "This message contains a known prompt-injection phrase. It was triaged before that rule existed, so the AI's draft has been discarded."
                    : "The AI model flagged this message as an attempt to instruct it, so its draft was discarded."}{" "}
                Blocking the sender closes their open messages and skips everything they send in future: no AI call, no reply.
              </p>
              {senderBlocked ? (
                <p className="rounded-lg bg-zinc-50 px-3 py-2 text-zinc-700 ring-1 ring-zinc-200">{email} is already on the blocklist.</p>
              ) : (
                <label className="block">
                  <span className="text-xs font-medium text-slate-500">Reason (saved with the block)</span>
                  <input
                    value={blockReason}
                    onChange={(e) => setBlockReason(e.target.value)}
                    className="mt-1 h-9 w-full rounded-lg bg-white px-3 text-sm ring-1 ring-slate-200 ring-inset focus:ring-2 focus:ring-red-400 focus:outline-none"
                  />
                </label>
              )}
              <div className="flex flex-col-reverse gap-2 border-t border-slate-100 pt-4 sm:flex-row sm:items-center">
                {!writeAnyway && (
                  <button onClick={() => setWriteAnyway(true)} className="text-left text-xs text-slate-500 underline-offset-2 hover:text-slate-800 hover:underline">
                    Not an attack? Write a reply instead
                  </button>
                )}
                <div className="flex-1 text-xs text-amber-700 sm:text-center">
                  {needName ? "Sign in to review." : !email && "No sender email, so this sender cannot be blocked."}
                </div>
                <Button
                  variant="secondary"
                  disabled={needName || !!busy}
                  loading={busy === "reject"}
                  onClick={() => run("reject", { note: "Manipulation attempt: closed without reply" })}
                >
                  Dismiss, no reply
                </Button>
                <Button
                  variant="destructive"
                  icon={<Ban className="size-4" />}
                  disabled={needName || !email || !!busy}
                  loading={busy === "block"}
                  onClick={() => run("block", { note: blockReason })}
                >
                  {senderBlocked ? "Close as blocked" : "Block sender"}
                </Button>
              </div>
            </div>
          </section>
        )}

        {pending ? (
          (!quarantined || writeAnyway) && <Card
            title="Reply"
            actions={
              <div className="flex items-center gap-1">
                {editedFromAi && (
                  <Button size="sm" variant="ghost" icon={<Undo2 className="size-3.5" />} onClick={() => setText(item.draft_reply)}>
                    Restore AI draft
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<RefreshCw className="size-3.5" />}
                  loading={busy === "regenerate"}
                  disabled={!!busy}
                  title="Ask the AI for a fresh draft (discards your edits)"
                  onClick={async () => {
                    await run("regenerate");
                  }}
                >
                  Regenerate
                </Button>
              </div>
            }
          >
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && !needName && text.trim()) run("approve", { text });
              }}
              dir="auto"
              rows={8}
              placeholder={item.draft_reply ? "" : "The AI could not draft this one. Write the reply here."}
              className="w-full resize-y rounded-xl bg-slate-50/60 px-4 py-3 text-[15px] leading-relaxed text-slate-800 ring-1 ring-slate-200 ring-inset placeholder:text-slate-400 focus:bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none"
            />
            <div className="mt-2 flex items-center justify-between text-xs text-slate-400">
              <span>
                {words} words{editedFromAi && <span className="ml-2 rounded bg-indigo-50 px-1.5 py-0.5 text-indigo-600">edited by you</span>}
              </span>
              <span className="hidden sm:inline">
                {item.gmail && "Approving saves a Gmail draft · "}Ctrl + Enter to approve
              </span>
            </div>

            {rejecting ? (
              <div className="mt-4 rounded-xl bg-rose-50/60 p-3 ring-1 ring-rose-200">
                <label className="text-sm font-medium text-rose-800" htmlFor="reject-note">Why is this draft unsuitable? (optional)</label>
                <input
                  id="reject-note"
                  autoFocus
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && run("reject", { note })}
                  placeholder="e.g. needs a phone call instead, wrong tone…"
                  className="mt-2 h-9 w-full rounded-lg bg-white px-3 text-sm ring-1 ring-rose-200 ring-inset focus:ring-2 focus:ring-rose-400 focus:outline-none"
                />
                <div className="mt-3 flex justify-end gap-2">
                  <Button size="sm" variant="ghost" onClick={() => setRejecting(false)}>Cancel</Button>
                  <Button size="sm" variant="danger" icon={<X className="size-3.5" />} loading={busy === "reject"} onClick={() => run("reject", { note })}>
                    Reject draft
                  </Button>
                </div>
              </div>
            ) : (
              <div className="mt-4 flex flex-col-reverse gap-2 border-t border-slate-100 pt-4 sm:flex-row sm:items-center">
                <Button variant="danger" icon={<X className="size-4" />} disabled={needName || !!busy} onClick={() => setRejecting(true)}>
                  Reject
                </Button>
                <div className="flex-1 text-xs text-amber-700 sm:text-center">{needName && "Sign in to review."}</div>
                <Button
                  variant="secondary"
                  icon={<Save className="size-4" />}
                  disabled={needName || !dirty || !!busy}
                  loading={busy === "save"}
                  onClick={() => run("save", { text })}
                >
                  Save edit
                </Button>
                <Button
                  variant="success"
                  icon={<Check className="size-4" />}
                  disabled={needName || !text.trim() || !!busy}
                  loading={busy === "approve"}
                  onClick={() => run("approve", { text })}
                >
                  Approve reply
                </Button>
              </div>
            )}
          </Card>
        ) : item.review_status === "blocked" ? (
          <section className="rounded-2xl bg-zinc-900 px-5 py-4 text-sm text-zinc-300 shadow-sm">
            <div className="flex items-center gap-2 font-semibold text-white">
              <Ban className="size-4" /> Sender blocked · not answered
            </div>
            <p className="mt-2">
              {item.intent === "blocked_sender"
                ? `${email} was already on the blocklist when this arrived, so it was never sent to the AI.`
                : `${email || "This sender"} was blocked by ${item.reviewed_by ?? "a reviewer"}${item.reviewed_at ? ` · ${formatWhen(item.reviewed_at)}` : ""}.`}
              {item.review_note && <span className="block text-zinc-400">Reason: {item.review_note}</span>}
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button size="sm" variant="secondary" icon={<RotateCcw className="size-3.5" />} disabled={needName || !!busy} loading={busy === "reopen"} onClick={() => run("reopen")}>
                Reopen this message
              </Button>
              {senderBlocked && (
                <Button size="sm" variant="ghost" className="text-zinc-300 hover:bg-zinc-800 hover:text-white" disabled={needName || !!busy} loading={busy === "unblock"} onClick={() => run("unblock")}>
                  Unblock sender
                </Button>
              )}
            </div>
          </section>
        ) : (
          <Card
            title={item.review_status === "approved" ? "Approved reply" : "Rejected"}
            actions={
              <div className="flex gap-1">
                {item.review_status === "approved" && item.final_reply && (
                  <Button size="sm" variant="ghost" icon={<Copy className="size-3.5" />} onClick={() => copy(item.final_reply!)}>
                    Copy
                  </Button>
                )}
                <Button size="sm" variant="ghost" icon={<RotateCcw className="size-3.5" />} loading={busy === "reopen"} disabled={needName} onClick={() => run("reopen")}>
                  Reopen
                </Button>
              </div>
            }
          >
            {item.review_status === "approved" ? (
              <p className="rounded-xl bg-emerald-50/50 px-4 py-3 text-[15px] leading-relaxed whitespace-pre-wrap text-slate-800 ring-1 ring-emerald-100" dir="auto">
                {item.final_reply}
              </p>
            ) : (
              <p className="text-sm text-slate-600">{item.review_note ? `Reason: ${item.review_note}` : "No reason given."}</p>
            )}
            <p className="mt-3 text-xs text-slate-500">
              {item.review_status === "approved" ? "Approved" : "Rejected"} by <span className="font-medium text-slate-700">{item.reviewed_by}</span> · {formatWhen(item.reviewed_at)}
              {item.review_status === "approved" &&
                (item.gmail ? " · not sent: send the Gmail draft yourself." : " · not sent: copy it or export the approved CSV.")}
            </p>
            {item.review_status === "approved" && item.gmail && (
              item.gmail.draft_id && !item.gmail.draft_error ? (
                <p className="mt-3 flex items-center gap-2 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600 ring-1 ring-slate-200">
                  <Mail className="size-3.5 text-rose-500" />
                  Saved as a draft in {item.gmail.mailbox}, in the candidate's thread.
                  <a href={gmailDraftsUrl(item.gmail.mailbox)} target="_blank" rel="noreferrer" className="ml-auto font-medium text-indigo-600 hover:underline">
                    Open Gmail drafts
                  </a>
                </p>
              ) : (
                <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-amber-200">
                  <AlertTriangle className="size-3.5 shrink-0" />
                  <span className="flex-1">{item.gmail.draft_error ?? "No Gmail draft yet."}</span>
                  <Button size="sm" variant="secondary" icon={<Mail className="size-3.5" />} loading={busy === "draft"} disabled={needName || !!busy} onClick={() => run("draft")}>
                    Create Gmail draft
                  </Button>
                </div>
              )
            )}
          </Card>
        )}

        {item.events && item.events.length > 0 && (
          <Card title="History" icon={<History className="size-3.5" />}>
            <ol className="relative space-y-4 border-l border-slate-200 pl-5">
              {item.events.map((e, i) => (
                <li key={i} className="relative">
                  <span
                    className={cx(
                      "absolute top-1.5 -left-[25px] size-2.5 rounded-full ring-4 ring-white",
                      e.action === "approved" ? "bg-emerald-500" : e.action === "rejected" ? "bg-rose-500" : "bg-slate-300",
                    )}
                  />
                  <div className="text-sm text-slate-700">
                    <span className="font-medium">{e.reviewer}</span> {EVENT_TEXT[e.action] ?? e.action}
                    <span className="ml-2 text-xs text-slate-400">{formatWhen(e.at)}</span>
                  </div>
                  {e.note && <div className="mt-0.5 text-xs text-slate-500">{e.note}</div>}
                  {e.action === "approved" && e.before_text && e.after_text && e.before_text.trim() !== e.after_text.trim() && (
                    <div className="mt-1 text-xs text-indigo-600">Reviewer changed the AI draft before approving</div>
                  )}
                </li>
              ))}
            </ol>
          </Card>
        )}
      </div>
    </div>
  );
}
