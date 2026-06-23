import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";

// Now Showing tab: live playback state + shuttle controls (ARCHITECTURE.md §6.2).
export default function NowShowing() {
  const [state, setState] = useState(null);
  const [showings, setShowings] = useState([]);
  const [pick, setPick] = useState("");
  const [error, setError] = useState("");
  const [previewTs, setPreviewTs] = useState(() => Date.now());
  const [previewOk, setPreviewOk] = useState(true);

  // Cache-bust the output preview image every 3 seconds.
  useEffect(() => {
    const t = setInterval(() => setPreviewTs(Date.now()), 3000);
    return () => clearInterval(t);
  }, []);

  const poll = useCallback(async () => {
    try {
      setState(await api.playbackState());
      setError("");
    } catch (e) {
      setError(e.message);
      setState(null);
    }
  }, []);

  useEffect(() => {
    poll();
    const t = setInterval(poll, 1500);
    api.listShowings().then(setShowings).catch(() => {});
    return () => clearInterval(t);
  }, [poll]);

  const act = async (fn) => {
    try {
      await fn();
      await poll();
    } catch (e) {
      setError(e.message);
    }
  };

  const isPlaying = state?.state === "playing";
  const isPaused = state?.state === "paused";
  const current = showings.find((s) => s.id === state?.showing_id);

  return (
    <>
      <h2 style={{ marginTop: 0 }}>Now Showing</h2>
      {error && <p className="error">Playback service: {error}</p>}

      <div className="card">
        <div className="spread">
          <div>
            <div className="muted">Current state</div>
            <div style={{ fontSize: 22, fontWeight: 700 }}>
              {(state?.state || "unknown").toUpperCase()}
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div className="muted">Showing</div>
            <div style={{ fontSize: 18 }}>
              {current ? current.title : state?.showing_id ? `#${state.showing_id}` : "—"}
            </div>
          </div>
        </div>
        <div className="muted" style={{ marginTop: 8 }}>
          Item: {state?.current_item || "—"} · Position:{" "}
          {state ? `${Math.floor(state.position_seconds / 60)}:${String(
            Math.floor(state.position_seconds % 60),
          ).padStart(2, "0")}` : "—"}
        </div>

        <div className="shuttle">
          <button className="btn secondary" onClick={() => act(api.resume)} disabled={!isPaused}>▶ Play</button>
          <button className="btn secondary" onClick={() => act(api.pause)} disabled={!isPlaying}>⏸ Pause</button>
          <button className="btn danger" onClick={() => act(api.stop)} disabled={!isPlaying && !isPaused}>⏹ End Show</button>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="muted">Output preview</div>
        <div className="preview-wrap">
          <img
            className="preview-img"
            alt="Current output"
            src={api.playbackPreviewUrl(previewTs)}
            onLoad={() => setPreviewOk(true)}
            onError={() => setPreviewOk(false)}
            style={{ display: previewOk ? "block" : "none" }}
          />
          {!previewOk && (
            <div className="preview-empty muted">No preview — nothing playing</div>
          )}
        </div>
        <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
          Live shot of the output · refreshes every 3s
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="muted">Run a show immediately</div>
        <div className="row" style={{ marginTop: 8 }}>
          <select value={pick} onChange={(e) => setPick(e.target.value)}>
            <option value="">Select a showing…</option>
            {showings.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title} — {new Date(s.scheduled_start).toLocaleString()}
              </option>
            ))}
          </select>
          <button
            className="btn"
            disabled={!pick}
            onClick={() => act(() => api.startShow(Number(pick)))}
          >
            ⏯ Start Show
          </button>
        </div>
      </div>
    </>
  );
}
