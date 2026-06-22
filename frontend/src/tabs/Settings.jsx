import { useEffect, useState } from "react";
import { api } from "../api.js";

// Settings: assign playback to video outputs (SDI / GPU / both) and pick the
// audio output + mode. Output devices are discovered from the playback service.
export default function Settings() {
  const [outputs, setOutputs] = useState({ video: [], audio: [] });
  const [videoIds, setVideoIds] = useState([]);
  const [audioId, setAudioId] = useState("");
  const [audioMode, setAudioMode] = useState("passthrough");
  const [hardware, setHardware] = useState(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    api.getSettings().then((s) => {
      setVideoIds(s.video_output_ids || []);
      setAudioId(s.audio_output_id || "");
      setAudioMode(s.audio_mode || "passthrough");
    }).catch((e) => setError(e.message));
    api.listOutputs().then(setOutputs).catch((e) =>
      setError(`Could not list outputs (${e.message}). Is the playback service up?`),
    );
    api.getHardware().then(setHardware).catch(() => {});
  }, []);

  const toggleVideo = (id) =>
    setVideoIds((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]));

  async function save() {
    setError("");
    setMsg("");
    try {
      await api.updateSettings({
        video_output_ids: videoIds,
        audio_output_id: audioId || null,
        audio_mode: audioMode,
      });
      setMsg("Settings saved ✓");
    } catch (e) {
      setError(e.message);
    }
  }

  const typeBadge = (t) => <span className="badge" style={{ marginLeft: 8 }}>{t}</span>;

  return (
    <>
      <h2 style={{ marginTop: 0 }}>Settings</h2>
      {error && <p className="error">{error}</p>}
      {msg && <p className="ok">{msg}</p>}

      <div className="row" style={{ alignItems: "flex-start", gap: 24 }}>
        <div className="card" style={{ flex: 1 }}>
          <h3 style={{ marginTop: 0 }}>Video output</h3>
          <p className="muted">
            Select one or more targets. Choosing both SDI and a GPU output mirrors
            playback to both.
          </p>
          {outputs.video.length === 0 && <p className="muted">No video outputs detected.</p>}
          {outputs.video.map((o) => (
            <label key={o.id} className="card row" style={{ cursor: "pointer", marginBottom: 8 }}>
              <input
                type="checkbox"
                checked={videoIds.includes(o.id)}
                onChange={() => toggleVideo(o.id)}
              />
              <span style={{ flex: 1 }}>
                {o.name}
                {typeBadge(o.type)}
              </span>
            </label>
          ))}
        </div>

        <div className="card" style={{ flex: 1 }}>
          <h3 style={{ marginTop: 0 }}>Audio output</h3>
          <p className="muted">Single audio target plus how to send it.</p>
          {outputs.audio.map((o) => (
            <label key={o.id} className="card row" style={{ cursor: "pointer", marginBottom: 8 }}>
              <input
                type="radio"
                name="audio"
                checked={audioId === o.id}
                onChange={() => setAudioId(o.id)}
              />
              <span style={{ flex: 1 }}>
                {o.name}
                {typeBadge(o.type)}
              </span>
            </label>
          ))}

          <div style={{ marginTop: 12 }}>
            <div className="muted">Audio mode</div>
            <select value={audioMode} onChange={(e) => setAudioMode(e.target.value)}>
              <option value="passthrough">Passthrough (bitstream Atmos/DTS:X/etc.)</option>
              <option value="pcm">Decode to PCM</option>
            </select>
          </div>
        </div>
      </div>

      <div style={{ marginTop: 16 }}>
        <button className="btn" onClick={save}>Save settings</button>
      </div>

      <div className="card" style={{ marginTop: 24 }}>
        <h3 style={{ marginTop: 0 }}>Detected hardware</h3>
        {!hardware || hardware.available === false ? (
          <p className="muted">
            No discovery data yet. Run <code>sudo htm → Re-discover hardware</code> on
            the server (e.g. after swapping a GPU, DeckLink, or printer).
          </p>
        ) : (
          <div className="stack">
            <div className="row" style={{ gap: 24 }}>
              <span>Primary GPU: <b>{hardware.primary_gpu_vendor}</b> <span className="muted">(decode: {hardware.primary_hwaccel})</span></span>
              <span>DeckLink SDI: <b>{hardware.has_decklink ? "yes" : "no"}</b></span>
            </div>
            {(hardware.gpus || []).map((g, i) => (
              <div key={i} className="muted">GPU — {g.vendor} {g.model} ({g.kind}, decode {g.decode})</div>
            ))}
            {(hardware.decklink || []).map((d, i) => (
              <div key={i} className="muted">Capture — {d.model}</div>
            ))}
            {(hardware.printers || []).map((p, i) => (
              <div key={i} className="muted">Printer — {p.vendor} {p.name}</div>
            ))}
            {(hardware.audio || []).map((a, i) => (
              <div key={i} className="muted">Audio — card {a.index}: {a.name}</div>
            ))}
            <div className="muted" style={{ fontSize: 12 }}>
              Discovered {hardware.discovered_at}. Re-run with <code>sudo htm</code>.
            </div>
          </div>
        )}
      </div>
    </>
  );
}
