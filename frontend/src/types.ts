export type ReviewStatus = "pending" | "approved" | "rejected" | "blocked";

export interface ReviewEvent {
  action: "edited" | "approved" | "rejected" | "reopened" | "regenerated" | "blocked" | "unblocked";
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
  events?: ReviewEvent[];
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
  status: "running" | "done" | "failed";
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
