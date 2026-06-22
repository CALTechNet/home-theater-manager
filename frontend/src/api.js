// Tiny fetch wrapper around the backend REST API.
const BASE = "/api";

async function req(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(BASE + path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* ignore */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  // media
  listMedia: (kind) => req("GET", `/media${kind ? `?kind=${kind}` : ""}`),
  scanMedia: () => req("POST", "/media/scan"),
  tagMedia: (id, body) => req("PATCH", `/media/${id}`, body),

  // showings
  listShowings: (start, end) => {
    const qs = new URLSearchParams();
    if (start) qs.set("start", start);
    if (end) qs.set("end", end);
    const q = qs.toString();
    return req("GET", `/showings${q ? `?${q}` : ""}`);
  },
  getShowing: (id) => req("GET", `/showings/${id}`),
  createShowing: (body) => req("POST", "/showings", body),
  updateShowing: (id, body) => req("PATCH", `/showings/${id}`, body),
  deleteShowing: (id) => req("DELETE", `/showings/${id}`),

  // tickets
  seatGrid: () => req("GET", "/tickets/seat-grid"),
  listTickets: (showingId) =>
    req("GET", `/tickets${showingId ? `?showing_id=${showingId}` : ""}`),
  createTicket: (body) => req("POST", "/tickets", body),
  // PDF is served directly (not JSON) — build the URL for the browser to open.
  ticketPdfUrl: (id, style) => `/api/tickets/${id}/pdf?style=${style}`,

  // settings
  getSettings: () => req("GET", "/settings"),
  updateSettings: (body) => req("PUT", "/settings", body),
  listOutputs: () => req("GET", "/settings/outputs"),
  getHardware: () => req("GET", "/settings/hardware"),

  // playback
  playbackState: () => req("GET", "/playback/state"),
  startShow: (id) => req("POST", `/playback/start/${id}`),
  pause: () => req("POST", "/playback/pause"),
  resume: () => req("POST", "/playback/resume"),
  stop: () => req("POST", "/playback/stop"),
};
