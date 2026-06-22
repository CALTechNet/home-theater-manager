import { useEffect, useState } from "react";
import { api } from "../api.js";
import MovieInfo from "./MovieInfo.jsx";

// New Showing wizard (ARCHITECTURE.md §1): showtime -> feature -> trailers ->
// review runtime -> create. Runtime is computed server-side (rounded to nearest
// minute) and echoed back on create.
const STEPS = ["Showtime", "Feature", "Trailers", "Review"];

function fmtDur(seconds) {
  const m = Math.round(seconds / 60);
  return `${m} min`;
}

export default function Wizard({ onClose, onCreated }) {
  const [step, setStep] = useState(0);
  const [title, setTitle] = useState("");
  const [start, setStart] = useState("");
  const [features, setFeatures] = useState([]);
  const [trailers, setTrailers] = useState([]);
  const [featureId, setFeatureId] = useState(null);
  const [trailerIds, setTrailerIds] = useState([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.listMedia("feature").then(setFeatures).catch((e) => setError(e.message));
    api.listMedia("trailer").then(setTrailers).catch((e) => setError(e.message));
  }, []);

  const feature = features.find((f) => f.id === featureId);
  const chosenTrailers = trailerIds
    .map((id) => trailers.find((t) => t.id === id))
    .filter(Boolean);
  const totalSeconds =
    (feature?.duration_seconds || 0) +
    chosenTrailers.reduce((s, t) => s + (t.duration_seconds || 0), 0);

  const canNext =
    (step === 0 && start) ||
    (step === 1 && featureId) ||
    step === 2 ||
    step === 3;

  const toggleTrailer = (id) =>
    setTrailerIds((ids) =>
      ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id],
    );

  async function submit() {
    setSaving(true);
    setError("");
    try {
      const items = [
        ...trailerIds.map((id) => ({ media_id: id, role: "trailer" })),
        { media_id: featureId, role: "feature" },
      ];
      const created = await api.createShowing({
        title: title || feature?.title || "Untitled",
        scheduled_start: start,
        feature_id: featureId,
        items,
      });
      onCreated(created);
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="spread">
          <h2 style={{ margin: 0 }}>New Showing — {STEPS[step]}</h2>
          <button className="btn secondary" onClick={onClose}>✕</button>
        </div>
        <div className="steps">
          {STEPS.map((s, i) => (
            <div key={s} className={`step ${i <= step ? "done" : ""}`} />
          ))}
        </div>

        {error && <p className="error">{error}</p>}

        {step === 0 && (
          <div className="stack">
            <div>
              <div className="muted">Title (optional)</div>
              <input
                style={{ width: "100%" }}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Defaults to feature title"
              />
            </div>
            <div>
              <div className="muted">Showtime</div>
              <input
                type="datetime-local"
                value={start}
                onChange={(e) => setStart(e.target.value)}
              />
            </div>
          </div>
        )}

        {step === 1 && (
          <div className="stack">
            <div className="muted">Pick the feature film</div>
            {features.length === 0 && (
              <p className="muted">No features tagged. Tag media in the Media tab.</p>
            )}
            {features.map((f) => (
              <label key={f.id} className="card row" style={{ cursor: "pointer" }}>
                <input
                  type="radio"
                  name="feature"
                  checked={featureId === f.id}
                  onChange={() => setFeatureId(f.id)}
                />
                <span style={{ flex: 1 }}>
                  <b>{f.title}</b>{" "}
                  {f.is_hdr10 && <span className="badge hdr">HDR10</span>}
                  <div className="muted">
                    {fmtDur(f.duration_seconds)} · {f.width}×{f.height} ·{" "}
                    {f.aspect_ratio} · {f.audio_format || f.video_codec}
                  </div>
                </span>
              </label>
            ))}
            {feature && <MovieInfo media={feature} />}
          </div>
        )}

        {step === 2 && (
          <div className="stack">
            <div className="muted">Select trailers to play before the feature</div>
            {trailers.length === 0 && <p className="muted">No trailers tagged yet.</p>}
            {trailers.map((t) => (
              <label key={t.id} className="card row" style={{ cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={trailerIds.includes(t.id)}
                  onChange={() => toggleTrailer(t.id)}
                />
                <span style={{ flex: 1 }}>
                  <b>{t.title}</b>
                  <div className="muted">{fmtDur(t.duration_seconds)}</div>
                </span>
              </label>
            ))}
          </div>
        )}

        {step === 3 && (
          <div className="stack">
            <div className="card">
              <div className="spread">
                <b>{title || feature?.title}</b>
                <span className="muted">{start.replace("T", " ")}</span>
              </div>
              <hr style={{ borderColor: "var(--border)" }} />
              <div className="muted">Playlist</div>
              {chosenTrailers.map((t) => (
                <div key={t.id} className="row spread">
                  <span>🎞 {t.title}</span>
                  <span className="muted">{fmtDur(t.duration_seconds)}</span>
                </div>
              ))}
              <div className="row spread">
                <span>🎬 {feature?.title}</span>
                <span className="muted">{fmtDur(feature?.duration_seconds || 0)}</span>
              </div>
              <hr style={{ borderColor: "var(--border)" }} />
              <div className="spread">
                <b>Total runtime</b>
                <b>{fmtDur(totalSeconds)}</b>
              </div>
            </div>
            <MovieInfo media={feature} />
          </div>
        )}

        <div className="spread" style={{ marginTop: 18 }}>
          <button
            className="btn secondary"
            disabled={step === 0}
            onClick={() => setStep((s) => s - 1)}
          >
            Back
          </button>
          {step < 3 ? (
            <button className="btn" disabled={!canNext} onClick={() => setStep((s) => s + 1)}>
              Next
            </button>
          ) : (
            <button className="btn" disabled={saving} onClick={submit}>
              {saving ? "Creating…" : "Create Showing"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
