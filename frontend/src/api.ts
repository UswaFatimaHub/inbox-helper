import type { BlockedSender, Item, Me, Meta, Run } from "./types";

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
  item: (id: number) => request<Item>(`/api/items/${id}`),
  startSample: () => request<{ id: number }>("/api/runs/sample", { method: "POST" }),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ id: number }>("/api/runs", { method: "POST", body: form });
  },
  // the reviewer is the signed-in user; the server records it
  review: (id: number, body: { action: "save" | "approve" | "reject" | "reopen"; text?: string; note?: string }) =>
    request<Item>(`/api/items/${id}/review`, json(body)),
  regenerate: (id: number) => request<Item>(`/api/items/${id}/regenerate`, { method: "POST" }),
  blocked: () => request<BlockedSender[]>("/api/blocked"),
  block: (id: number, reason?: string) => request<Item>(`/api/items/${id}/block`, json({ reason })),
  unblock: (email: string) => request<{ unblocked: string }>(`/api/blocked/${encodeURIComponent(email)}`, { method: "DELETE" }),
  retry: (runId: number) => request<{ id: number }>(`/api/runs/${runId}/retry`, { method: "POST" }),
  exportUrl: (runId: number) => `/api/runs/${runId}/export.csv`,
  auditUrl: (runId: number) => `/api/runs/${runId}/audit.json`,
};
