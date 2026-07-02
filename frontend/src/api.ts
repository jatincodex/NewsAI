import { BACKEND_URL } from "./theme";

const base = `${BACKEND_URL}/api`;

async function req(path: string, opts: RequestInit = {}) {
  const res = await fetch(`${base}${path}`, {
    ...opts,
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`HTTP ${res.status}: ${t}`);
  }
  return res.json();
}

export const api = {
  stats: () => req("/stats"),
  posts: (status?: string) =>
    req(status ? `/posts?status=${encodeURIComponent(status)}` : "/posts"),
  postsEnriched: (statuses = "verified,debunked", limit = 50) =>
    req(`/posts/enriched?statuses=${encodeURIComponent(statuses)}&limit=${limit}`),
  post: (id: string) => req(`/posts/${id}`),
  adminQueue: () => req("/admin/queue"),
  approve: (id: string) =>
    req(`/admin/posts/${id}/approve`, { method: "POST", body: JSON.stringify({}) }),
  reject: (id: string) =>
    req(`/admin/posts/${id}/reject`, { method: "POST", body: JSON.stringify({}) }),
  ingest: (count = 3) =>
    req("/ingest", { method: "POST", body: JSON.stringify({ count }) }),
  renderJobs: () => req("/render-jobs"),
};
