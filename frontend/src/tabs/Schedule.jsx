import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import Wizard from "../components/Wizard.jsx";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const HOURS = Array.from({ length: 24 }, (_, h) => h); // 0..23, midnight -> midnight
const HOUR_PX = 44; // vertical pixels per hour
const DAY_PX = 24 * HOUR_PX;
// Default visible window: 11am -> 10pm. Full 24h stays scrollable up/down.
const DEFAULT_START_HOUR = 11;
const DEFAULT_END_HOUR = 22; // 10 PM (inclusive)
const VISIBLE_HOURS = DEFAULT_END_HOUR - DEFAULT_START_HOUR + 1;
const CAL_BODY_PX = VISIBLE_HOURS * HOUR_PX;

function startOfWeek(d) {
  const date = new Date(d);
  const day = (date.getDay() + 6) % 7; // Mon=0
  date.setHours(0, 0, 0, 0);
  date.setDate(date.getDate() - day);
  return date;
}

function minutesIntoDay(d) {
  return d.getHours() * 60 + d.getMinutes();
}

function hourLabel(h) {
  const ampm = h < 12 ? "AM" : "PM";
  const display = h % 12 === 0 ? 12 : h % 12;
  return `${display} ${ampm}`;
}

function fmtTime(d) {
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/**
 * Pack a day's showings into lanes so overlapping showings sit side by side,
 * and flag the ones that actually collide (runtime overlaps another's start).
 */
function layoutDay(dayShowings) {
  const sorted = [...dayShowings].sort(
    (a, b) => new Date(a.scheduled_start) - new Date(b.scheduled_start),
  );
  const laneEnds = []; // last end-minute per lane
  const blocks = sorted.map((s) => {
    const start = new Date(s.scheduled_start);
    const startMin = minutesIntoDay(start);
    const endMin = startMin + (s.computed_runtime_min || 0);
    let lane = laneEnds.findIndex((end) => end <= startMin);
    if (lane === -1) {
      lane = laneEnds.length;
      laneEnds.push(endMin);
    } else {
      laneEnds[lane] = endMin;
    }
    return { s, startMin, endMin, lane };
  });

  const overlapping = new Set();
  for (let i = 0; i < blocks.length; i++) {
    for (let j = i + 1; j < blocks.length; j++) {
      if (blocks[i].startMin < blocks[j].endMin && blocks[j].startMin < blocks[i].endMin) {
        overlapping.add(blocks[i].s.id);
        overlapping.add(blocks[j].s.id);
      }
    }
  }
  return { blocks, lanes: Math.max(1, laneEnds.length), overlapping };
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
  const calBodyRef = useRef(null);

  // Open on the 11am–10pm band; the rest of the day is a scroll away.
  useEffect(() => {
    if (calBodyRef.current) {
      calBodyRef.current.scrollTop = DEFAULT_START_HOUR * HOUR_PX;
    }
  }, []);

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

  // Per-day layout (lanes + overlap flags) and week-level totals.
  const days = DAYS.map((label, i) => {
    const date = new Date(weekStart);
    date.setDate(date.getDate() + i);
    return { label, date, ...layoutDay(byDay(i)) };
  });
  const totalShowtimes = showings.length;
  const totalOverlaps = days.reduce((n, d) => n + d.overlapping.size, 0);

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

      <div className="spread" style={{ marginBottom: 12 }}>
        <span className="muted">
          {totalShowtimes} showtime{totalShowtimes === 1 ? "" : "s"} this week
        </span>
        {totalOverlaps > 0 ? (
          <span className="error">⚠ {totalOverlaps} overlapping showing{totalOverlaps === 1 ? "" : "s"}</span>
        ) : (
          <span className="ok">No overlaps</span>
        )}
      </div>

      {error && <p className="error">{error}</p>}

      <div className="cal card">
        <div className="cal-head">
          <div className="cal-gutter-head" />
          {days.map(({ label, date, blocks, overlapping }) => (
            <div className="cal-day-head" key={label}>
              <div className="cal-day-name">{label} {date.getDate()}</div>
              <div className="muted" style={{ fontSize: 12 }}>
                {blocks.length} showtime{blocks.length === 1 ? "" : "s"}
                {overlapping.size > 0 && <span className="error"> · ⚠ {overlapping.size}</span>}
              </div>
            </div>
          ))}
        </div>

        <div className="cal-body" ref={calBodyRef} style={{ height: CAL_BODY_PX }}>
          <div className="cal-gutter" style={{ height: DAY_PX }}>
            {HOURS.map((h) => (
              <div className="cal-hour-label" key={h} style={{ height: HOUR_PX }}>
                {hourLabel(h)}
              </div>
            ))}
          </div>

          {days.map(({ label, blocks, lanes, overlapping }) => (
            <div className="cal-day" key={label} style={{ height: DAY_PX }}>
              {HOURS.map((h) => (
                <div className="cal-hour-line" key={h} style={{ top: h * HOUR_PX }} />
              ))}
              {blocks.map(({ s, startMin, lane }) => {
                const top = (startMin / 60) * HOUR_PX;
                const height = Math.max(((s.computed_runtime_min || 0) / 60) * HOUR_PX, 22);
                const width = 100 / lanes;
                const isOverlap = overlapping.has(s.id);
                return (
                  <div
                    className={`cal-event${isOverlap ? " overlap" : ""}`}
                    key={s.id}
                    onClick={() => setSelected(s)}
                    style={{
                      top,
                      height,
                      left: `calc(${lane * width}% + 2px)`,
                      width: `calc(${width}% - 4px)`,
                    }}
                    title={`${s.title || "(untitled)"} · ${fmtTime(new Date(s.scheduled_start))} · ${s.computed_runtime_min}m`}
                  >
                    <div className="t">{s.title || "(untitled)"}</div>
                    <div className="cal-event-meta">
                      {fmtTime(new Date(s.scheduled_start))} · {s.computed_runtime_min}m
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
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
