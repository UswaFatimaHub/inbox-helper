export interface Me {
  email: string;
  name: string;
  mode: "google" | "dev";
}

export type ReviewStatus = "pending" | "approved" | "rejected" | "blocked";

export interface ReviewEvent {
  action:
    | "edited" | "approved" | "rejected" | "reopened" | "regenerated" | "blocked" | "unblocked" | "quarantined"
    | "drafted" | "draft_deleted" | "draft_failed";
  reviewer: string;
  at: string;
  before_text: string | null;
  after_text: string | null;
  note: string | null;
}

export interface Item {
  id: number;
  run_id: number;
  message_id: string;
  received_at: string;
  candidate_name: string;
  candidate_email: string;
  role: string;
  subject: string;
  body: string;
  intent: string;
  secondary_intent: string | null;
  confidence: number;
  flags: string[];
  priority_review: boolean;
  reason: string;
  draft_reply: string;
  lane: string;
  model: string;
  prompt_version: string;
  latency_s: number | null;
  error: string | null;
  review_status: ReviewStatus;
  final_reply: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  gmail: GmailInfo | null; // set when the message was imported from Gmail
  events?: ReviewEvent[];
  highlights?: Highlight[]; // detail only: what to mark in the body
}

/** A span of the body to mark: a known injection phrase, or an identifier hidden from the AI (NATIONAL_ID, ...). */
export interface Highlight {
  start: number;
  end: number;
  kind: string;
}

export interface GmailInfo {
  mailbox: string;
  thread_id: string;
  draft_id: string | null;
  drafted_at: string | null;
  draft_error: string | null;
}

export interface GmailStatus {
  enabled: boolean;
  missing: string[];
  account: string;
  connected: boolean;
  connected_by: string | null;
  connected_at: string | null;
  last_fetch_at: string | null;
  error: string | null; // the connection stopped working; connect again
  fetch: FetchProgress | null; // set while "Fetch new emails" runs
}

/** The reviewer's greeting and sign-off; null means the team default. */
export interface Signature {
  greeting: string | null;
  sign_off: string | null;
  defaults: { greeting: string; sign_off: string };
}

export interface FetchProgress {
  stage: "searching" | "downloading" | "queueing";
  found: number;
  downloaded: number;
  started_at: string;
}

export interface GmailFetch {
  id: number | null; // the new run, or null when there was nothing new
  imported: number;
  errors: InputError[];
}

export interface InputError {
  row: number;
  message_id: string;
  error: string;
}

export interface Run {
  id: number;
  created_at: string;
  finished_at: string | null;
  input_name: string;
  profile: string;
  prompt_version: string;
  status: "queued" | "running" | "done" | "failed";
  total: number;
  processed: number;
  elapsed_s: number | null;
  error: string | null;
  input_errors: InputError[];
  lanes: { name: string; calls: number; failures: number; disabled: boolean }[];
  by_status: Partial<Record<ReviewStatus, number>>;
  by_intent: Record<string, number>;
  priority: number;
}

export interface BlockedSender {
  email: string;
  reason: string | null;
  blocked_by: string;
  blocked_at: string;
  source_item_id: number | null;
}

export interface Meta {
  intents: Record<string, string>;
  system_intents: string[];
  flags: Record<string, string>;
  priority_flags: string[];
  profile: string;
  prompt_version: string;
  lanes: { name: string; models: string[] }[];
}
