async function json(res) {
  if (!res.ok) throw new Error(`${res.status} ${await res.text().catch(() => "")}`);
  return res.json();
}

export const api = {
  health: () => fetch("/healthz").then(json),
  listRuns: () => fetch("/api/runs").then(json),
  startRun: (payload) =>
    fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(json),
  register: () => fetch("/api/register.json").then(json),
  verify: (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch("/api/verify", { method: "POST", body: fd }).then(json);
  },
};

// Durable (manifest) URLs are credential-free and never expire, but the bucket
// is private — so the browser asks the API to mint a short-lived signed URL.
const signCache = new Map();
export async function signedUrl(durableUrl) {
  if (!durableUrl) return null;
  if (signCache.has(durableUrl)) return signCache.get(durableUrl);
  const p = fetch(`/api/assets/sign?url=${encodeURIComponent(durableUrl)}`)
    .then(json)
    .then((d) => d.url)
    .catch(() => null);
  signCache.set(durableUrl, p);
  return p;
}

export function shortHash(h, n = 12) {
  return h ? `${h.slice(0, n)}…` : "—";
}

export function fmtTime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}
