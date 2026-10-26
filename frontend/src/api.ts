import type { BlockedSender, Item, Meta, Run } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
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
  review: (id: number, body: { action: "save" | "approve" | "reject" | "reopen"; reviewer: string; text?: string; note?: string }) =>
    request<Item>(`/api/items/${id}/review`, json(body)),
  regenerate: (id: number, reviewer: string) =>
    request<Item>(`/api/items/${id}/regenerate?reviewer=${encodeURIComponent(reviewer)}`, { method: "POST" }),
  blocked: () => request<BlockedSender[]>("/api/blocked"),
  block: (id: number, reviewer: string, reason?: string) => request<Item>(`/api/items/${id}/block`, json({ reviewer, reason })),
  unblock: (email: string, reviewer: string) =>
    request<{ unblocked: string }>(`/api/blocked/${encodeURIComponent(email)}?reviewer=${encodeURIComponent(reviewer)}`, { method: "DELETE" }),
  exportUrl: (runId: number) => `/api/runs/${runId}/export.csv`,
  auditUrl: (runId: number) => `/api/runs/${runId}/audit.json`,
};
