import { useEffect, useState } from "react";
import { api } from "../api.js";

// Settings: assign playback to video outputs (SDI / GPU / both) and pick the
// audio output + mode. Output devices are discovered from the playback service.
export default function Settings() {
  const [outputs, setOutputs] = useState({ video: [], audio: [] });
  const [videoIds, setVideoIds] = useState([]);
  const [audioId, setAudioId] = useState("");
  const [audioMode, setAudioMode] = useState("passthrough");
  const [idleMode, setIdleMode] = useState("black");
  const [idleScale, setIdleScale] = useState("fit");
  const [idleLogoPath, setIdleLogoPath] = useState("");
  const [logoFile, setLogoFile] = useState(null);
  const [timeFormat, setTimeFormat] = useState("12h");
  const [hardware, setHardware] = useState(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  const connectors = hardware?.connectors || [];

  useEffect(() => {
    api.getSettings().then((s) => {
      setVideoIds(s.video_output_ids || []);
      setAudioId(s.audio_output_id || "");
      setAudioMode(s.audio_mode || "passthrough");
      setIdleMode(s.idle_screen_mode || "black");
      setIdleScale(s.idle_logo_scale || "fit");
      setIdleLogoPath(s.idle_logo_path || "");
      setTimeFormat(s.time_format || "12h");
    }).catch((e) => setError(e.message));
    api.listOutputs().then(setOutputs).catch((e) =>
      setError(`Could not list outputs (${e.message}). Is the playback service up?`),
    );
    api.getHardware().then(setHardware).catch(() => {});
  }, []);

  const toggleVideo = (id) =>
    setVideoIds((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]));

  const displayForOutput = (output) => {
    if (output.drm_connector) {
      return connectors.find((c) => c.name === output.drm_connector) || {
        name: output.drm_connector,
        status: output.status,
        device: output.drm_device,
      };
    }
    if (output.id?.startsWith("gpu:")) {
      const name = output.id.split(":")[1];
      return connectors.find((c) => c.name === name);
    }
    return null;
  };

  async function save() {
    setError("");
    setMsg("");
    try {
      if (logoFile) {
        const uploaded = await api.uploadIdleLogo(logoFile);
        setIdleLogoPath(uploaded.idle_logo_path);
        setIdleMode("logo");
      }
      await api.updateSettings({
        video_output_ids: videoIds,
        audio_output_id: audioId || null,
        audio_mode: audioMode,
        idle_screen_mode: logoFile ? "logo" : idleMode,
        idle_logo_scale: idleScale,
        time_format: timeFormat,
      });
      setLogoFile(null);
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
          {outputs.video.map((o) => {
            const checked = videoIds.includes(o.id);
            const warn = o.reserved && checked;
            const display = displayForOutput(o);
            return (
              <label
                key={o.id}
                className="card row"
                style={{ cursor: "pointer", marginBottom: 8, opacity: o.reserved ? 0.7 : 1 }}
                title={o.reserved_reason || ""}
              >
                <input type="checkbox" checked={checked} onChange={() => toggleVideo(o.id)} />
                <span style={{ flex: 1 }}>
                  {o.name}
                  {typeBadge(o.type)}
                  {o.reserved && (
                    <span
                      style={{
                        marginLeft: 8,
                        fontSize: "0.75em",
                        padding: "1px 6px",
                        borderRadius: 4,
                        background: warn ? "#7a2e2e" : "#5a4a1a",
                        color: "#fff",
                      }}
                    >
                      console-reserved
                    </span>
                  )}
                  {warn && (
                    <div className="muted" style={{ color: "#e0a500", marginTop: 4 }}>
                      ⚠ {o.reserved_reason}
                    </div>
                  )}
                  {display && (
                    <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                      Display {display.name}
                      {display.status ? ` · ${display.status}` : ""}
                      {display.device ? ` · ${display.device}` : ""}
                    </div>
                  )}
                </span>
              </label>
            );
          })}
          {connectors.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div className="muted">Discovered displays</div>
              <div className="stack" style={{ marginTop: 6 }}>
                {connectors.map((c) => (
                  <div key={`${c.card || ""}-${c.name}`} className="muted" style={{ fontSize: 12 }}>
                    {c.name} · {c.status || "unknown"} · {c.device || c.card || "DRM"}
                  </div>
                ))}
              </div>
            </div>
          )}
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
                {o.alsa_device && (
                  <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                    ALSA {o.alsa_device}
                  </div>
                )}
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

      <div className="card" style={{ marginTop: 16 }}>
        <h3 style={{ marginTop: 0 }}>Idle screen</h3>
        <p className="muted">
          The playback service keeps control of the selected video outputs between shows.
        </p>

        <div className="row" style={{ alignItems: "flex-start", gap: 24 }}>
          <div style={{ flex: 1 }}>
            <div className="muted">When no trailers or movie are playing</div>
            <label className="chk" style={{ marginTop: 8 }}>
              <input
                type="radio"
                name="idle-mode"
                checked={idleMode === "black"}
                onChange={() => setIdleMode("black")}
              />
              Black screen
            </label>
            <label className="chk" style={{ marginTop: 8 }}>
              <input
                type="radio"
                name="idle-mode"
                checked={idleMode === "logo"}
                onChange={() => setIdleMode("logo")}
              />
              Logo
            </label>
          </div>

          <div style={{ flex: 1 }}>
            <div className="muted">Logo scaling</div>
            <select value={idleScale} onChange={(e) => setIdleScale(e.target.value)}>
              <option value="fit">Fit inside output</option>
              <option value="fill">Fill output</option>
            </select>
          </div>
        </div>

        <div style={{ marginTop: 12 }}>
          <div className="muted">3840x2160 logo image</div>
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            onChange={(e) => setLogoFile(e.target.files?.[0] || null)}
          />
          <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
            {logoFile ? logoFile.name : idleLogoPath ? idleLogoPath : "No logo uploaded"}
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3 style={{ marginTop: 0 }}>Display</h3>
        <div className="muted">Top-bar clock format</div>
        <select
          value={timeFormat}
          onChange={(e) => setTimeFormat(e.target.value)}
          style={{ marginTop: 8 }}
        >
          <option value="12h">12-hour (AM/PM)</option>
          <option value="24h">24-hour</option>
        </select>
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
            {(hardware.connectors || []).map((c, i) => (
              <div key={i} className="muted">Display — {c.name} ({c.status || "unknown"}, {c.device || c.card || "DRM"})</div>
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
            {(hardware.audio_outputs || []).map((a, i) => (
              <div key={i} className="muted">
                Audio output — {a.name} ({a.alsa_device})
              </div>
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
