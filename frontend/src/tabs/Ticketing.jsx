import { useEffect, useState } from "react";
import { api } from "../api.js";

// Tickets are generated server-side as PDFs (receipt or full-page color). The
// browser opens the PDF so the operator can print to any printer they have.
export default function Ticketing({ initialShowingId }) {
  const [showings, setShowings] = useState([]);
  const [grid, setGrid] = useState({ rows: [], numbers: [] });
  const [showingId, setShowingId] = useState(initialShowingId || "");
  const [seat, setSeat] = useState("");
  const [name, setName] = useState("");
  const [extras, setExtras] = useState({ drink: false, popcorn: false, candy: false });
  const [style, setStyle] = useState("receipt");
  const [pdfUrl, setPdfUrl] = useState("");
  const [history, setHistory] = useState([]);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    api.listShowings().then(setShowings).catch((e) => setError(e.message));
    api.seatGrid().then(setGrid).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (showingId) api.listTickets(showingId).then(setHistory).catch(() => {});
    else setHistory([]);
  }, [showingId, msg]);

  // Open the PDF in a new tab and trigger the browser's print dialog.
  function openAndPrint(url) {
    setPdfUrl(url);
    const win = window.open(url, "_blank");
    if (win) {
      win.addEventListener("load", () => {
        try {
          win.focus();
          win.print();
        } catch {
          /* user can print manually */
        }
      });
    }
  }

  async function generate() {
    setError("");
    setMsg("");
    try {
      const t = await api.createTicket({
        showing_id: Number(showingId),
        seat: seat || null,
        name: name || null,
        incl_drink: extras.drink,
        incl_popcorn: extras.popcorn,
        incl_candy: extras.candy,
      });
      const url = api.ticketPdfUrl(t.id, style);
      setMsg(`Ticket #${t.id} created`);
      openAndPrint(url);
    } catch (e) {
      setError(e.message);
    }
  }

  function reprint(id) {
    openAndPrint(api.ticketPdfUrl(id, style));
  }

  return (
    <>
      <h2 style={{ marginTop: 0 }}>Ticketing</h2>
      {error && <p className="error">{error}</p>}
      {msg && <p className="ok">{msg}</p>}

      <div className="row" style={{ alignItems: "flex-start", gap: 24 }}>
        <div className="card" style={{ flex: 1 }}>
          <div className="stack">
            <div>
              <div className="muted">Showing</div>
              <select
                style={{ width: "100%" }}
                value={showingId}
                onChange={(e) => setShowingId(e.target.value)}
              >
                <option value="">Select a showing…</option>
                {showings.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.title} — {new Date(s.scheduled_start).toLocaleString()}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <div className="muted">Seat</div>
              <div className="seatgrid" style={{ gridTemplateColumns: `repeat(${grid.numbers.length}, auto)` }}>
                {grid.rows.flatMap((row) =>
                  grid.numbers.map((n) => {
                    const code = `${row}${n}`;
                    return (
                      <button
                        key={code}
                        className={`seat ${seat === code ? "sel" : ""}`}
                        onClick={() => setSeat(seat === code ? "" : code)}
                      >
                        {code}
                      </button>
                    );
                  }),
                )}
              </div>
            </div>

            <div>
              <div className="muted">Name</div>
              <input
                style={{ width: "100%" }}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Guest name (optional)"
              />
            </div>

            <div>
              <div className="muted">Included</div>
              <div style={{ marginTop: 6 }}>
                {["drink", "popcorn", "candy"].map((k) => (
                  <label key={k} className="chk">
                    <input
                      type="checkbox"
                      checked={extras[k]}
                      onChange={(e) => setExtras({ ...extras, [k]: e.target.checked })}
                    />
                    {k[0].toUpperCase() + k.slice(1)}
                  </label>
                ))}
              </div>
            </div>

            <div>
              <div className="muted">Ticket style</div>
              <select value={style} onChange={(e) => setStyle(e.target.value)}>
                <option value="receipt">Thermal receipt (80mm)</option>
                <option value="fullpage">Full-page color (8.5×11)</option>
              </select>
            </div>

            <button className="btn" disabled={!showingId} onClick={generate}>
              🎟 Generate & Print
            </button>
          </div>
        </div>

        <div className="card" style={{ flex: 1 }}>
          <div className="muted">PDF preview</div>
          {pdfUrl ? (
            <iframe
              title="ticket"
              src={pdfUrl}
              style={{ width: "100%", height: 420, border: "1px solid var(--border)", borderRadius: 6, marginTop: 8, background: "#fff" }}
            />
          ) : (
            <p className="muted">Generate a ticket to preview the PDF here.</p>
          )}

          <div className="muted" style={{ marginTop: 16 }}>
            Printed for this showing ({history.length})
          </div>
          <table>
            <tbody>
              {history.map((t) => (
                <tr key={t.id}>
                  <td>#{t.id}</td>
                  <td>{t.seat || "—"}</td>
                  <td>{t.name || "—"}</td>
                  <td className="muted">copy {t.copy_index}</td>
                  <td>
                    <button className="btn secondary" onClick={() => reprint(t.id)}>Reprint</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
