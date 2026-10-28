export const INTENT_LABELS: Record<string, string> = {
  application_status: "Application status",
  interview_scheduling: "Interviews",
  documents: "Documents",
  offer_and_compensation: "Offer & pay",
  withdrawal: "Withdrawal",
  accommodation_request: "Accommodation",
  complaint: "Complaint",
  general_question: "General question",
  other: "Other / unclear",
  manipulation_attempt: "Manipulation",
  blocked_sender: "Blocked sender",
};

// Tailwind classes per intent: [dot, chip]
export const INTENT_STYLES: Record<string, { dot: string; chip: string }> = {
  application_status: { dot: "bg-sky-500", chip: "bg-sky-50 text-sky-700 ring-sky-200" },
  interview_scheduling: { dot: "bg-violet-500", chip: "bg-violet-50 text-violet-700 ring-violet-200" },
  documents: { dot: "bg-amber-500", chip: "bg-amber-50 text-amber-800 ring-amber-200" },
  offer_and_compensation: { dot: "bg-emerald-500", chip: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  withdrawal: { dot: "bg-slate-400", chip: "bg-slate-100 text-slate-700 ring-slate-200" },
  accommodation_request: { dot: "bg-teal-500", chip: "bg-teal-50 text-teal-700 ring-teal-200" },
  complaint: { dot: "bg-rose-500", chip: "bg-rose-50 text-rose-700 ring-rose-200" },
  general_question: { dot: "bg-indigo-500", chip: "bg-indigo-50 text-indigo-700 ring-indigo-200" },
  other: { dot: "bg-zinc-400", chip: "bg-zinc-100 text-zinc-700 ring-zinc-200" },
  manipulation_attempt: { dot: "bg-red-600", chip: "bg-red-50 text-red-700 ring-red-300" },
  blocked_sender: { dot: "bg-zinc-700", chip: "bg-zinc-800 text-zinc-50 ring-zinc-800" },
};

export const FLAG_LABELS: Record<string, string> = {
  ambiguous: "Unclear request",
  multiple_intents: "Several requests",
  sensitive: "Sensitive",
  unsupported_request: "Not supported by policy",
  needs_info_not_available: "Needs recruiter's records",
  prompt_injection: "Tries to instruct the AI",
  hostile_tone: "Upset candidate",
  non_english: "Not in English",
  invalid_label: "Invalid AI label",
  low_confidence: "Low AI confidence",
  unverified_date_or_time: "Unverified date/time",
  possible_hiring_decision: "Implies a decision",
  mentions_money: "Mentions money",
  contains_placeholder: "Has placeholder",
  claims_completed_action: "Claims an action was done",
  ai_self_reference: "Speaks as AI / 'I'",
  long_draft: "Long draft",
  invalid_email: "Odd email address",
  duplicate_message: "Duplicate message",
  processing_failed: "AI failed — write manually",
  injection_pattern: "Known injection phrase",
  blocked_sender: "Blocked sender",
  personal_data_hidden: "Personal data hidden from AI",
};

/** high = the draft itself may be wrong; attention = handle with care; info = context only */
export type Severity = "high" | "attention" | "info";

const HIGH = new Set([
  "prompt_injection", "possible_hiring_decision", "mentions_money", "unverified_date_or_time",
  "claims_completed_action", "ai_self_reference", "processing_failed", "invalid_label", "contains_placeholder",
  "injection_pattern", "blocked_sender",
]);
const ATTENTION = new Set(["sensitive", "hostile_tone", "ambiguous", "low_confidence", "unsupported_request"]);

export function flagSeverity(flag: string): Severity {
  if (HIGH.has(flag)) return "high";
  if (ATTENTION.has(flag)) return "attention";
  return "info";
}

export const SEVERITY_STYLES: Record<Severity, string> = {
  high: "bg-rose-50 text-rose-700 ring-rose-200",
  attention: "bg-amber-50 text-amber-800 ring-amber-200",
  info: "bg-slate-50 text-slate-600 ring-slate-200",
};

export const intentLabel = (k: string) => INTENT_LABELS[k] ?? k;
export const flagLabel = (k: string) => FLAG_LABELS[k] ?? k.replace(/_/g, " ");

export function formatWhen(value: string | null | undefined): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function initials(name: string): string {
  // words only, so "Sarah (HR)" gives "SH" rather than "S("
  const parts = name.split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  if (!parts.length) return "?";
  return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

/** Short name for a run: where its messages came from. */
export function runSource(inputName: string): string {
  if (inputName.startsWith("Gmail: ")) return "Gmail inbox";
  return inputName.replace(/\s*\(messages\.csv\)$/, "");
}

/** 45 → "45s", 125 → "2m 05s" */
export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

export const shortModel = (m: string) => m.split("/").pop()?.replace(":free", "") ?? m;
