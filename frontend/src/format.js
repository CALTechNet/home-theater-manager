// Shared formatters for media technicals.

export function fmtRuntime(seconds) {
  const m = Math.round((seconds || 0) / 60);
  return `${m} min`;
}

export function fmtSize(bytes) {
  if (!bytes) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
}

export function fmtBitrate(bps) {
  if (!bps) return "—";
  if (bps >= 1_000_000) return `${(bps / 1_000_000).toFixed(1)} Mbps`;
  return `${Math.round(bps / 1000)} kbps`;
}

export function fmtResolution(m) {
  if (!m.width || !m.height) return "—";
  const tag =
    m.height >= 2160 ? " (4K)" : m.height >= 1080 ? " (1080p)" : m.height >= 720 ? " (720p)" : "";
  return `${m.width}×${m.height}${tag}`;
}
