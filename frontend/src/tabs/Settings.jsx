import { useEffect, useState } from "react";
import { api } from "../api.js";

const DEFAULT_TONE_MAPPING = {
  enabled: true,
  mode: "dynamic",
  output_profile_id: "lumagen-auto",
  target_container: "sdr2020",
  target_nits: 100,
  gamma: "2.4",
  color_space: "bt2020",
  max_light_multiplier: 6,
  dynamic_pad: 4,
  desaturation: "auto",
  low_display_ratio: 31,
  max_cll_mode: "auto",
  max_cll_fallback_nits: 1000,
  static_crossover_nits: 1000,
  hdr_metadata: "strip",
  custom_profile: {},
};

const DEFAULT_VIDEO_MODE = {
  match_policy: "frame_rate",
  base_output_profile_id: "lumagen-auto",
  resolution: "profile",
  frame_rate: "source",
  dynamic_range: "source",
};

const FIELD = {
  display: "grid",
  gap: 6,
  flex: "1 1 190px",
  minWidth: 170,
};

function mergeDefaults(defaults, value) {
  return { ...defaults, ...(value || {}) };
}

function formatContainer(value) {
  return {
    sdr2020: "SDR BT.2020",
    sdr709: "SDR Rec.709",
    hdr10: "HDR10 pass-through",
  }[value] || value;
}

function field(label, children) {
  return (
    <label style={FIELD}>
      <span className="muted">{label}</span>
      {children}
    </label>
  );
}

// Settings: assign playback outputs, tone mapping, idle screen, and display policy.
export default function Settings() {
  const [outputs, setOutputs] = useState({ video: [], audio: [] });
  const [profiles, setProfiles] = useState([]);
  const [videoIds, setVideoIds] = useState([]);
  const [audioId, setAudioId] = useState("");
  const [audioMode, setAudioMode] = useState("passthrough");
  const [idleMode, setIdleMode] = useState("black");
  const [idleScale, setIdleScale] = useState("fit");
  const [idleLogoPath, setIdleLogoPath] = useState("");
  const [logoFile, setLogoFile] = useState(null);
  const [timeFormat, setTimeFormat] = useState("12h");
  const [toneMapping, setToneMapping] = useState(DEFAULT_TONE_MAPPING);
  const [videoMode, setVideoMode] = useState(DEFAULT_VIDEO_MODE);
  const [hardware, setHardware] = useState(null);
  const [discovering, setDiscovering] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  const connectors = hardware?.connectors || [];
  const selectedProfile = profiles.find((p) => p.id === toneMapping.output_profile_id);
  const baseProfile = profiles.find((p) => p.id === videoMode.base_output_profile_id);

  const loadOutputs = () => api.listOutputs().then(setOutputs).catch((e) =>
    setError(`Could not list outputs (${e.message}). Is the playback service up?`),
  );
  const loadHardware = () => api.getHardware().then(setHardware).catch(() => {});

  useEffect(() => {
    api.videoProfiles().then((catalog) => {
      setProfiles(catalog.output_profiles || []);
      setToneMapping((current) => mergeDefaults(catalog.tone_mapping_defaults || current, current));
      setVideoMode((current) => mergeDefaults(catalog.video_mode_defaults || current, current));
    }).catch(() => {});
    api.getSettings().then((s) => {
      setVideoIds(s.video_output_ids || []);
      setAudioId(s.audio_output_id || "");
      setAudioMode(s.audio_mode || "passthrough");
      setIdleMode(s.idle_screen_mode || "black");
      setIdleScale(s.idle_logo_scale || "fit");
      setIdleLogoPath(s.idle_logo_path || "");
      setTimeFormat(s.time_format || "12h");
      setToneMapping(mergeDefaults(DEFAULT_TONE_MAPPING, s.tone_mapping));
      setVideoMode(mergeDefaults(DEFAULT_VIDEO_MODE, s.video_mode));
    }).catch((e) => setError(e.message));
    loadOutputs();
    loadHardware();
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

  const updateTone = (key, value) => setToneMapping((current) => ({ ...current, [key]: value }));
  const updateVideoMode = (key, value) => setVideoMode((current) => ({ ...current, [key]: value }));
  const updateToneNumber = (key, value) => updateTone(key, Number(value));
  const updateCustomProfile = (key, value) =>
    setToneMapping((current) => ({
      ...current,
      custom_profile: { ...(current.custom_profile || {}), [key]: value },
    }));

  const selectToneProfile = (id) => {
    const profile = profiles.find((p) => p.id === id);
    setToneMapping((current) => ({
      ...current,
      output_profile_id: id,
      ...(profile ? {
        target_container: profile.output_container,
        target_nits: profile.target_nits,
        gamma: profile.gamma,
        color_space: profile.color_space,
        max_light_multiplier: profile.max_light_multiplier,
        dynamic_pad: profile.dynamic_pad,
        desaturation: profile.desaturation,
        low_display_ratio: profile.low_display_ratio,
      } : {}),
    }));
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
        tone_mapping: toneMapping,
        video_mode: videoMode,
      });
      setLogoFile(null);
      setMsg("Settings saved ✓");
    } catch (e) {
      setError(e.message);
    }
  }

  async function rediscover() {
    setError("");
    setMsg("");
    setDiscovering(true);
    try {
      const discovered = await api.rediscoverHardware();
      setHardware(discovered);
      await loadOutputs();
      setMsg("Hardware rediscovered ✓");
    } catch (e) {
      setError(e.message);
    } finally {
      setDiscovering(false);
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
        <div className="spread" style={{ alignItems: "flex-start", gap: 16 }}>
          <div>
            <h3 style={{ marginTop: 0 }}>HDR to SDR tone mapping</h3>
            <p className="muted" style={{ marginBottom: 0 }}>
              Lumagen-style dynamic tone mapping defaults with editable output targets.
            </p>
          </div>
          <label className="chk" style={{ marginRight: 0 }}>
            <input
              type="checkbox"
              checked={toneMapping.enabled}
              onChange={(e) => updateTone("enabled", e.target.checked)}
            />
            Enabled
          </label>
        </div>

        <div className="row" style={{ alignItems: "flex-start", flexWrap: "wrap", marginTop: 14 }}>
          {field("Output profile", (
            <select value={toneMapping.output_profile_id} onChange={(e) => selectToneProfile(e.target.value)}>
              {profiles.map((profile) => (
                <option key={profile.id} value={profile.id}>{profile.name}</option>
              ))}
              {profiles.length === 0 && <option value={toneMapping.output_profile_id}>Current profile</option>}
            </select>
          ))}
          {field("Tone map mode", (
            <select value={toneMapping.mode} onChange={(e) => updateTone("mode", e.target.value)}>
              <option value="dynamic">Dynamic</option>
              <option value="static">Static</option>
              <option value="passthrough">Pass-through</option>
            </select>
          ))}
          {field("Output container", (
            <select value={toneMapping.target_container} onChange={(e) => updateTone("target_container", e.target.value)}>
              <option value="sdr2020">SDR BT.2020</option>
              <option value="sdr709">SDR Rec.709</option>
              <option value="hdr10">HDR10 pass-through</option>
            </select>
          ))}
          {field("HDR metadata", (
            <select value={toneMapping.hdr_metadata} onChange={(e) => updateTone("hdr_metadata", e.target.value)}>
              <option value="strip">Strip for SDR output</option>
              <option value="pass_through">Pass through</option>
            </select>
          ))}
        </div>

        {selectedProfile && (
          <div
            style={{
              marginTop: 12,
              padding: "10px 12px",
              border: "1px solid var(--border)",
              borderRadius: 8,
            }}
          >
            <b>{selectedProfile.manufacturer}</b>
            <span className="muted"> · {selectedProfile.category} · {selectedProfile.description}</span>
          </div>
        )}

        <div className="row" style={{ alignItems: "flex-start", flexWrap: "wrap", marginTop: 14 }}>
          {field("Target nits", (
            <input
              type="number"
              min="20"
              max="1000"
              value={toneMapping.target_nits}
              onChange={(e) => updateToneNumber("target_nits", e.target.value)}
            />
          ))}
          {field("Max light multiplier", (
            <input
              type="number"
              min="1"
              max="12"
              step="0.5"
              value={toneMapping.max_light_multiplier}
              onChange={(e) => updateToneNumber("max_light_multiplier", e.target.value)}
            />
          ))}
          {field("Dynamic pad", (
            <input
              type="range"
              min="0"
              max="7"
              value={toneMapping.dynamic_pad}
              onChange={(e) => updateToneNumber("dynamic_pad", e.target.value)}
            />
          ))}
          {field("High luminance desat", (
            <select value={toneMapping.desaturation} onChange={(e) => updateTone("desaturation", e.target.value)}>
              <option value="auto">Auto</option>
              <option value="off">Off</option>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          ))}
          {field("Low display ratio", (
            <input
              type="number"
              min="0"
              max="100"
              value={toneMapping.low_display_ratio}
              onChange={(e) => updateToneNumber("low_display_ratio", e.target.value)}
            />
          ))}
          {field("MaxCLL mode", (
            <select value={toneMapping.max_cll_mode} onChange={(e) => updateTone("max_cll_mode", e.target.value)}>
              <option value="auto">Auto</option>
              <option value="always">Always use fallback</option>
            </select>
          ))}
          {field("Fallback MaxCLL nits", (
            <input
              type="number"
              min="100"
              max="10000"
              value={toneMapping.max_cll_fallback_nits}
              onChange={(e) => updateToneNumber("max_cll_fallback_nits", e.target.value)}
            />
          ))}
          {field("Static crossover nits", (
            <input
              type="number"
              min="100"
              max="10000"
              value={toneMapping.static_crossover_nits}
              onChange={(e) => updateToneNumber("static_crossover_nits", e.target.value)}
            />
          ))}
          {field("Gamma", (
            <select value={toneMapping.gamma} onChange={(e) => updateTone("gamma", e.target.value)}>
              <option value="2.2">2.2</option>
              <option value="2.35">2.35</option>
              <option value="2.4">2.4</option>
              <option value="2.6">2.6</option>
              <option value="pq">PQ</option>
            </select>
          ))}
          {field("Color space", (
            <select value={toneMapping.color_space} onChange={(e) => updateTone("color_space", e.target.value)}>
              <option value="bt2020">BT.2020</option>
              <option value="p3">P3</option>
              <option value="rec709">Rec.709</option>
            </select>
          ))}
        </div>

        {toneMapping.output_profile_id === "custom" && (
          <div className="row" style={{ alignItems: "flex-start", flexWrap: "wrap", marginTop: 14 }}>
            {field("Custom profile name", (
              <input
                value={toneMapping.custom_profile?.name || ""}
                onChange={(e) => updateCustomProfile("name", e.target.value)}
              />
            ))}
            {field("Manufacturer", (
              <input
                value={toneMapping.custom_profile?.manufacturer || ""}
                onChange={(e) => updateCustomProfile("manufacturer", e.target.value)}
              />
            ))}
            {field("Profile note", (
              <input
                value={toneMapping.custom_profile?.description || ""}
                onChange={(e) => updateCustomProfile("description", e.target.value)}
              />
            ))}
          </div>
        )}
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3 style={{ marginTop: 0 }}>Output mode matching</h3>
        <div className="row" style={{ alignItems: "flex-start", flexWrap: "wrap" }}>
          {field("Match source", (
            <select value={videoMode.match_policy} onChange={(e) => updateVideoMode("match_policy", e.target.value)}>
              <option value="none">None</option>
              <option value="frame_rate">Frame rate</option>
              <option value="dynamic_range">HDR/SDR range</option>
              <option value="both">Frame rate and range</option>
            </select>
          ))}
          {field("Base output profile", (
            <select
              value={videoMode.base_output_profile_id}
              onChange={(e) => updateVideoMode("base_output_profile_id", e.target.value)}
            >
              {profiles.map((profile) => (
                <option key={profile.id} value={profile.id}>{profile.name}</option>
              ))}
              {profiles.length === 0 && <option value={videoMode.base_output_profile_id}>Current profile</option>}
            </select>
          ))}
          {field("Resolution", (
            <select value={videoMode.resolution} onChange={(e) => updateVideoMode("resolution", e.target.value)}>
              <option value="profile">Profile default</option>
              <option value="source">Match source</option>
              <option value="3840x2160">3840x2160</option>
              <option value="4096x2160">4096x2160</option>
              <option value="1920x1080">1920x1080</option>
            </select>
          ))}
          {field("Frame rate", (
            <select value={videoMode.frame_rate} onChange={(e) => updateVideoMode("frame_rate", e.target.value)}>
              <option value="source">Match source</option>
              <option value="23.976">23.976</option>
              <option value="24">24</option>
              <option value="25">25</option>
              <option value="29.97">29.97</option>
              <option value="30">30</option>
              <option value="50">50</option>
              <option value="59.94">59.94</option>
              <option value="60">60</option>
            </select>
          ))}
          {field("Dynamic range", (
            <select value={videoMode.dynamic_range} onChange={(e) => updateVideoMode("dynamic_range", e.target.value)}>
              <option value="source">Match source</option>
              <option value="sdr">Force SDR</option>
              <option value="hdr">Force HDR</option>
            </select>
          ))}
        </div>
        <div className="muted" style={{ marginTop: 12 }}>
          Base: {baseProfile ? `${baseProfile.name} · ${formatContainer(baseProfile.output_container)}` : "Current profile"}
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3 style={{ marginTop: 0 }}>EDID capabilities</h3>
        {connectors.length === 0 ? (
          <p className="muted">No discovered display data is available.</p>
        ) : (
          <div className="stack">
            {connectors.map((c) => {
              const modes = Array.isArray(c.modes) ? c.modes : [];
              const shownModes = modes.slice(0, 10);
              return (
                <div
                  key={`${c.card || ""}-${c.name}-edid`}
                  style={{
                    paddingBottom: 12,
                    borderBottom: "1px solid var(--border)",
                  }}
                >
                  <div>
                    <b>{c.name}</b>
                    <span className="muted"> · {c.status || "unknown"} · {c.device || c.card || "DRM"}</span>
                  </div>
                  <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                    EDID {c.edid_present ? `available (${c.edid_bytes || 0} bytes)` : "not reported"}
                    {c.edid_sha1 ? ` · ${c.edid_sha1}` : ""}
                  </div>
                  <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                    Modes: {shownModes.length > 0 ? shownModes.join(", ") : "none reported"}
                    {modes.length > shownModes.length ? `, +${modes.length - shownModes.length} more` : ""}
                  </div>
                </div>
              );
            })}
          </div>
        )}
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
        <div className="spread" style={{ marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>Detected hardware</h3>
          <button className="btn secondary" onClick={rediscover} disabled={discovering}>
            {discovering ? "Re-discovering…" : "Re-discover"}
          </button>
        </div>
        {!hardware || hardware.available === false ? (
          <p className="muted">
            No discovery data yet. Click <b>Re-discover</b> after swapping a GPU,
            display, audio interface, DeckLink, or printer.
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
              <div key={i} className="muted">
                Display — {c.name} ({c.status || "unknown"}, {c.device || c.card || "DRM"})
                {c.edid_present ? ` · EDID ${c.edid_bytes || 0} bytes` : ""}
              </div>
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
