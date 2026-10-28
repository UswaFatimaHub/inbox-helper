import type { BlockedSender, GmailFetch, GmailStatus, InputError, Item, Me, Meta, Run, Signature } from "./types";

/** A file or the sample was added to the queue: messages already in it are skipped. */
export type Started = { id: number; added: number; skipped: number; errors: InputError[] };

/** Thrown (and announced with a "signed-out" window event) when the session is missing or has expired. */
export class SignedOutError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (res.status === 401) {
    window.dispatchEvent(new Event("signed-out"));
    throw new SignedOutError("Your session has ended. Sign in again.");
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  me: () => request<Me>("/api/me"),
  logout: () => fetch("/api/auth/logout", { method: "POST" }),
  loginUrl: "/api/auth/google/login",
  meta: () => request<Meta>("/api/meta"),
  runs: () => request<Run[]>("/api/runs"),
  run: (id: number) => request<Run>(`/api/runs/${id}`),
  items: (runId: number) => request<Item[]>(`/api/runs/${runId}/items`),
  queue: () => request<Item[]>("/api/items"),
  item: (id: number) => request<Item>(`/api/items/${id}`),
  startSample: () => request<Started>("/api/runs/sample", { method: "POST" }),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Started>("/api/runs", { method: "POST", body: form });
  },
  // the reviewer is the signed-in user; the server records it
  review: (id: number, body: { action: "save" | "approve" | "reject" | "reopen"; text?: string; note?: string }) =>
    request<Item>(`/api/items/${id}/review`, json(body)),
  regenerate: (id: number) => request<Item>(`/api/items/${id}/regenerate`, { method: "POST" }),
  blocked: () => request<BlockedSender[]>("/api/blocked"),
  block: (id: number, reason?: string) => request<Item>(`/api/items/${id}/block`, json({ reason })),
  unblock: (email: string) => request<{ unblocked: string }>(`/api/blocked/${encodeURIComponent(email)}`, { method: "DELETE" }),
  retry: (runId: number) => request<{ id: number }>(`/api/runs/${runId}/retry`, { method: "POST" }),
  signature: () => request<Signature>("/api/settings/signature"),
  saveSignature: (body: { greeting: string; sign_off: string }) =>
    request<Signature>("/api/settings/signature", { ...json(body), method: "PUT" }),
  gmailStatus: () => request<GmailStatus>("/api/gmail/status"),
  gmailConnectUrl: "/api/gmail/connect",
  gmailFetch: () => request<GmailFetch>("/api/gmail/fetch", { method: "POST" }),
  gmailDisconnect: () => fetch("/api/gmail/disconnect", { method: "POST" }),
  gmailDraft: (id: number) => request<Item>(`/api/items/${id}/gmail-draft`, { method: "POST" }),
  exportUrl: "/api/export.csv",
  auditUrl: (runId: number) => `/api/runs/${runId}/audit.json`,
};
