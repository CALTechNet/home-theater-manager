import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import Wizard from "../components/Wizard.jsx";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function startOfWeek(d) {
  const date = new Date(d);
  const day = (date.getDay() + 6) % 7; // Mon=0
  date.setHours(0, 0, 0, 0);
  date.setDate(date.getDate() - day);
  return date;
}

function isoLocal(d) {
  // YYYY-MM-DDTHH:MM:SS in local time (backend stores naive local datetimes).
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(
    d.getHours(),
  )}:${p(d.getMinutes())}:00`;
}

export default function Schedule({ onPrintTickets }) {
  const [weekStart, setWeekStart] = useState(() => startOfWeek(new Date()));
  const [showings, setShowings] = useState([]);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    const end = new Date(weekStart);
    end.setDate(end.getDate() + 7);
    api
      .listShowings(isoLocal(weekStart), isoLocal(end))
      .then(setShowings)
      .catch((e) => setError(e.message));
  }, [weekStart]);

  useEffect(() => {
    load();
  }, [load]);

  const byDay = (i) => {
    const day = new Date(weekStart);
    day.setDate(day.getDate() + i);
    return showings.filter((s) => {
      const sd = new Date(s.scheduled_start);
      return (
        sd.getFullYear() === day.getFullYear() &&
        sd.getMonth() === day.getMonth() &&
        sd.getDate() === day.getDate()
      );
    });
  };

  const shiftWeek = (delta) => {
    const d = new Date(weekStart);
    d.setDate(d.getDate() + delta * 7);
    setWeekStart(d);
  };

  return (
    <>
      <div className="spread" style={{ marginBottom: 16 }}>
        <div className="row">
          <button className="btn secondary" onClick={() => shiftWeek(-1)}>← Prev</button>
          <button className="btn secondary" onClick={() => setWeekStart(startOfWeek(new Date()))}>
            This week
          </button>
          <button className="btn secondary" onClick={() => shiftWeek(1)}>Next →</button>
          <span className="muted">
            Week of {weekStart.toLocaleDateString()}
          </span>
        </div>
        <button className="btn" onClick={() => setWizardOpen(true)}>+ New Showing</button>
      </div>

      {error && <p className="error">{error}</p>}

      <div className="week">
        {DAYS.map((label, i) => {
          const day = new Date(weekStart);
          day.setDate(day.getDate() + i);
          return (
            <div className="day" key={label}>
              <h4>{label} {day.getDate()}</h4>
              {byDay(i).map((s) => (
                <div className="show-chip" key={s.id} onClick={() => setSelected(s)}>
                  <div className="t">{s.title || "(untitled)"}</div>
                  <div className="muted">
                    {new Date(s.scheduled_start).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}{" "}
                    · {s.computed_runtime_min}m · {s.status}
                  </div>
                </div>
              ))}
            </div>
          );
        })}
      </div>

      {wizardOpen && (
        <Wizard
          onClose={() => setWizardOpen(false)}
          onCreated={() => {
            setWizardOpen(false);
            load();
          }}
        />
      )}

      {selected && (
        <ShowingEditor
          showing={selected}
          onClose={() => setSelected(null)}
          onChanged={() => {
            setSelected(null);
            load();
          }}
          onPrintTickets={onPrintTickets}
        />
      )}
    </>
  );
}

function ShowingEditor({ showing, onClose, onChanged, onPrintTickets }) {
  const [start, setStart] = useState(showing.scheduled_start.slice(0, 16));
  const [title, setTitle] = useState(showing.title);
  const [error, setError] = useState("");

  async function save() {
    try {
      await api.updateShowing(showing.id, {
        title,
        scheduled_start: start + ":00",
      });
      onChanged();
    } catch (e) {
      setError(e.message);
    }
  }
  async function remove() {
    if (!confirm("Delete this showing?")) return;
    try {
      await api.deleteShowing(showing.id);
      onChanged();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="spread">
          <h2 style={{ margin: 0 }}>Edit Showing</h2>
          <button className="btn secondary" onClick={onClose}>✕</button>
        </div>
        {error && <p className="error">{error}</p>}
        <div className="stack" style={{ marginTop: 12 }}>
          <div>
            <div className="muted">Title</div>
            <input style={{ width: "100%" }} value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div>
            <div className="muted">Showtime</div>
            <input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div className="muted">
            Runtime: {showing.computed_runtime_min} min · Status: {showing.status}
          </div>
          <div className="card">
            <div className="muted">Playlist</div>
            {showing.items.map((it) => (
              <div className="row spread" key={it.id}>
                <span>{it.role === "feature" ? "🎬" : "🎞"} {it.media.title}</span>
                <span className="muted">{Math.round(it.media.duration_seconds / 60)}m</span>
              </div>
            ))}
          </div>
        </div>
        <div className="spread" style={{ marginTop: 18 }}>
          <button className="btn danger" onClick={remove}>Delete</button>
          <div className="row">
            <button className="btn secondary" onClick={() => onPrintTickets(showing.id)}>
              Print tickets
            </button>
            <button className="btn" onClick={save}>Save</button>
          </div>
        </div>
      </div>
    </div>
  );
}
