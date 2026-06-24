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

function sameLocalDay(a, b) {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

function startOfDay(d) {
  const date = new Date(d);
  date.setHours(0, 0, 0, 0);
  return date;
}

function hourLabel(h) {
  const ampm = h < 12 ? "AM" : "PM";
  const display = h % 12 === 0 ? 12 : h % 12;
  return `${display} ${ampm}`;
}

function fmtTime(d) {
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function fmtDur(seconds) {
  return `${Math.round((seconds || 0) / 60)}m`;
}

/**
 * Pack a day's showings into lanes so overlapping showings sit side by side,
 * and flag the ones that actually collide (runtime overlaps another's start).
 */
function segmentsForDay(showings, day) {
  const dayStart = startOfDay(day);
  const dayEnd = new Date(dayStart);
  dayEnd.setDate(dayEnd.getDate() + 1);
  return showings.flatMap((s) => {
    const start = new Date(s.scheduled_start);
    const end = new Date(start);
    end.setMinutes(end.getMinutes() + (s.computed_runtime_min || 0));
    if (start >= dayEnd || end <= dayStart) return [];
    const segmentStart = start < dayStart ? dayStart : start;
    const segmentEnd = end > dayEnd ? dayEnd : end;
    return [{
      s,
      key: `${s.id}-${dayStart.toISOString()}`,
      startMin: sameLocalDay(segmentStart, dayStart) ? minutesIntoDay(segmentStart) : 0,
      endMin: sameLocalDay(segmentEnd, dayStart) ? minutesIntoDay(segmentEnd) : 24 * 60,
      continuesFromPrev: start < dayStart,
      continuesNext: end > dayEnd,
    }];
  });
}

function layoutDay(showings, day) {
  const sorted = segmentsForDay(showings, day).sort(
    (a, b) => a.startMin - b.startMin || new Date(a.s.scheduled_start) - new Date(b.s.scheduled_start),
  );
  const laneEnds = []; // last end-minute per lane
  const blocks = sorted.map((segment) => {
    let lane = laneEnds.findIndex((end) => end <= segment.startMin);
    if (lane === -1) {
      lane = laneEnds.length;
      laneEnds.push(segment.endMin);
    } else {
      laneEnds[lane] = segment.endMin;
    }
    return { ...segment, lane };
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
    const start = new Date(weekStart);
    start.setDate(start.getDate() - 1);
    const end = new Date(weekStart);
    end.setDate(end.getDate() + 7);
    api
      .listShowings(isoLocal(start), isoLocal(end))
      .then(setShowings)
      .catch((e) => setError(e.message));
  }, [weekStart]);

  useEffect(() => {
    load();
  }, [load]);

  const shiftWeek = (delta) => {
    const d = new Date(weekStart);
    d.setDate(d.getDate() + delta * 7);
    setWeekStart(d);
  };

  // Per-day layout (lanes + overlap flags) and week-level totals.
  const days = DAYS.map((label, i) => {
    const date = new Date(weekStart);
    date.setDate(date.getDate() + i);
    return { label, date, ...layoutDay(showings, date) };
  });
  const totalShowtimes = showings.filter((s) => {
    const sd = new Date(s.scheduled_start);
    const end = new Date(weekStart);
    end.setDate(end.getDate() + 7);
    return sd >= weekStart && sd < end;
  }).length;
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
              {blocks.map(({ s, key, startMin, endMin, lane, continuesFromPrev, continuesNext }) => {
                const top = (startMin / 60) * HOUR_PX;
                const height = Math.max(((endMin - startMin) / 60) * HOUR_PX, 22);
                const width = 100 / lanes;
                const isOverlap = overlapping.has(s.id);
                const startLabel = continuesFromPrev ? "Continued" : fmtTime(new Date(s.scheduled_start));
                return (
                  <div
                    className={`cal-event${isOverlap ? " overlap" : ""}`}
                    key={key}
                    onClick={() => setSelected(s)}
                    style={{
                      top,
                      height,
                      left: `calc(${lane * width}% + 2px)`,
                      width: `calc(${width}% - 4px)`,
                    }}
                    title={`${s.title || "(untitled)"} · ${startLabel} · ${s.computed_runtime_min}m`}
                  >
                    <div className="t">{s.title || "(untitled)"}</div>
                    <div className="cal-event-meta">
                      {startLabel} · {s.computed_runtime_min}m{continuesNext ? " →" : ""}
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
  const [items, setItems] = useState(() => showing.items.map((it) => ({
    media_id: it.media_id,
    role: it.role,
    media: it.media,
  })));
  const [media, setMedia] = useState([]);
  const [addId, setAddId] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.listMedia("trailer"), api.listMedia("feature")])
      .then(([trailers, features]) => setMedia([...trailers, ...features]))
      .catch((e) => setError(e.message));
  }, []);

  const moveItem = (index, delta) => {
    setItems((current) => {
      const next = [...current];
      const target = index + delta;
      if (target < 0 || target >= next.length) return current;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  };

  const removeItem = (index) => {
    setItems((current) => current.filter((_, i) => i !== index));
  };

  const addItem = () => {
    const found = media.find((m) => String(m.id) === String(addId));
    if (!found) return;
    setItems((current) => [
      ...current,
      { media_id: found.id, role: found.kind === "feature" ? "feature" : "trailer", media: found },
    ]);
    setAddId("");
  };

  async function save() {
    try {
      await api.updateShowing(showing.id, {
        title,
        scheduled_start: start + ":00",
        items: items.map((it) => ({ media_id: it.media_id, role: it.role })),
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
            Runtime: {items.reduce((n, it) => n + Math.round((it.media?.duration_seconds || 0) / 60), 0)} min · Status: {showing.status}
          </div>
          <div className="card playlist-editor">
            <div className="spread" style={{ marginBottom: 10 }}>
              <div className="muted">Playlist</div>
              <div className="row playlist-add">
                <select value={addId} onChange={(e) => setAddId(e.target.value)}>
                  <option value="">Add media...</option>
                  {media.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.kind} - {m.title}
                    </option>
                  ))}
                </select>
                <button className="btn secondary" disabled={!addId} onClick={addItem}>Add</button>
              </div>
            </div>
            {items.map((it, index) => (
              <div className="playlist-row" key={`${it.media_id}-${index}`}>
                <button className="btn secondary icon-btn" disabled={index === 0} onClick={() => moveItem(index, -1)} title="Move up">
                  ↑
                </button>
                <button className="btn secondary icon-btn" disabled={index === items.length - 1} onClick={() => moveItem(index, 1)} title="Move down">
                  ↓
                </button>
                <span className={`badge ${it.role}`}>{it.role}</span>
                <span className="playlist-title" title={it.media?.path || it.media?.title}>
                  {it.media?.title || "(missing media)"}
                </span>
                <span className="muted playlist-duration">{fmtDur(it.media?.duration_seconds)}</span>
                <select
                  value={it.role}
                  onChange={(e) =>
                    setItems((current) =>
                      current.map((row, i) => (i === index ? { ...row, role: e.target.value } : row)),
                    )
                  }
                >
                  <option value="trailer">trailer</option>
                  <option value="feature">feature</option>
                </select>
                <button className="btn danger icon-btn" onClick={() => removeItem(index)} title="Remove">
                  ×
                </button>
              </div>
            ))}
            {items.length === 0 && <p className="muted">No playlist items.</p>}
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
