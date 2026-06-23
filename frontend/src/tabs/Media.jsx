import { useEffect, useState } from "react";
import { api } from "../api.js";
import { fmtBitrate, fmtResolution, fmtSize } from "../format.js";

export default function Media() {
  const [media, setMedia] = useState([]);
  const [storage, setStorage] = useState(null);
  const [error, setError] = useState("");
  const [scanning, setScanning] = useState(false);
  const [msg, setMsg] = useState("");

  const load = () => api.listMedia().then(setMedia).catch((e) => setError(e.message));
  const loadStorage = () => api.mediaStorage().then(setStorage).catch(() => setStorage(null));
  useEffect(() => { load(); loadStorage(); }, []);

  async function scan() {
    setScanning(true);
    setMsg("");
    setError("");
    try {
      const r = await api.scanMedia();
      setMsg(`Scanned ${r.scanned} files · ${r.added} added · ${r.updated} updated`);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setScanning(false);
    }
  }

  async function setKind(m, kind) {
    await api.tagMedia(m.id, { kind });
    load();
  }

  async function remove(m) {
    if (!confirm(`Remove "${m.title}" from the database? The file on disk is not deleted.`)) return;
    setError("");
    setMsg("");
    try {
      await api.deleteMedia(m.id);
      setMsg(`Removed "${m.title}"`);
      await load();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div className="media-page">
      {storage && <StorageBar storage={storage} />}

      <div className="spread" style={{ marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>Media Library</h2>
        <button className="btn" disabled={scanning} onClick={scan}>
          {scanning ? "Scanning…" : "Scan library"}
        </button>
      </div>
      {msg && <p className="ok">{msg}</p>}
      {error && <p className="error">{error}</p>}

      <div className="card media-table-card">
        <table className="media-table">
          <colgroup>
            <col className="media-col-title" />
            <col className="media-col-type" />
            <col className="media-col-duration" />
            <col className="media-col-resolution" />
            <col className="media-col-aspect" />
            <col className="media-col-codec" />
            <col className="media-col-hdr" />
            <col className="media-col-audio" />
            <col className="media-col-size" />
            <col className="media-col-bitrate" />
            <col className="media-col-actions" />
          </colgroup>
          <thead>
            <tr>
              <th>Title</th>
              <th>Type</th>
              <th>Duration</th>
              <th>Resolution</th>
              <th>Aspect</th>
              <th>Codec</th>
              <th>HDR</th>
              <th>Audio</th>
              <th>Size</th>
              <th>Bitrate</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {media.map((m) => (
              <tr key={m.id}>
                <td className="media-title-cell">
                  <b>{m.title}</b>
                  <div className="muted media-path">{m.path}</div>
                </td>
                <td><span className={`badge ${m.kind}`}>{m.kind}</span></td>
                <td>{Math.round(m.duration_seconds / 60)} min</td>
                <td>{fmtResolution(m)}</td>
                <td>{m.aspect_ratio || "—"}</td>
                <td>{m.video_codec}</td>
                <td>{m.is_hdr10 ? <span className="badge hdr">HDR10</span> : <span className="muted">SDR</span>}</td>
                <td className="muted media-audio">{m.audio_format || m.audio_summary}</td>
                <td>{fmtSize(m.file_size)}</td>
                <td>{fmtBitrate(m.bitrate)}</td>
                <td className="media-actions">
                  <div className="row media-action-row">
                    <button
                      className="btn secondary"
                      onClick={() => setKind(m, m.kind === "feature" ? "trailer" : "feature")}
                    >
                      Tag as {m.kind === "feature" ? "trailer" : "feature"}
                    </button>
                    <button className="btn danger" onClick={() => remove(m)}>
                      Remove
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {media.length === 0 && (
              <tr><td colSpan="11" className="muted">No media. Click "Scan library".</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// Storage usage summary for the media volume.
function StorageBar({ storage }) {
  const pct = Math.min(100, Math.max(0, storage.percent_used || 0));
  // Warn as the volume fills up.
  const tone = pct >= 90 ? "danger" : pct >= 75 ? "warn" : "ok";
  return (
    <div className="card storage" style={{ marginBottom: 16 }}>
      <div className="spread">
        <b>Storage</b>
        <span className="muted">
          {fmtSize(storage.used)} used of {fmtSize(storage.total)} ({pct}%) ·{" "}
          {fmtSize(storage.free)} free
        </span>
      </div>
      <div className="storage-track" style={{ marginTop: 8 }}>
        <div className={`storage-fill ${tone}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
