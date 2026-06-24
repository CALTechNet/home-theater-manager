import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api.js";

function statusClass(status) {
  if (status === "valid") return "scan-result ok";
  if (status === "already_scanned") return "scan-result warn";
  return "scan-result error";
}

function fmtDate(value) {
  return value ? new Date(value).toLocaleString() : "Not scanned";
}

export default function TicketScanner() {
  const [showings, setShowings] = useState([]);
  const [showingId, setShowingId] = useState("");
  const [tickets, setTickets] = useState([]);
  const [manualCode, setManualCode] = useState("");
  const [scannerOn, setScannerOn] = useState(false);
  const [cameraMsg, setCameraMsg] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const detectorRef = useRef(null);
  const scanningRef = useRef(false);
  const lastCodeRef = useRef("");

  const selectedShowing = useMemo(
    () => showings.find((s) => String(s.id) === String(showingId)),
    [showings, showingId],
  );

  function loadTickets(id = showingId) {
    if (!id) {
      setTickets([]);
      return Promise.resolve();
    }
    return api.listTickets(id).then(setTickets).catch((e) => setError(e.message));
  }

  useEffect(() => {
    api.listShowings().then(setShowings).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    loadTickets();
  }, [showingId]);

  useEffect(() => {
    return () => stopCamera();
  }, []);

  async function validate(rawCode) {
    const code = rawCode.trim();
    if (!code) return;
    setError("");
    try {
      const res = await api.validateTicket({
        code,
        showing_id: showingId ? Number(showingId) : null,
      });
      setResult(res);
      setManualCode("");
      await loadTickets(res.ticket?.showing_id || showingId);
      if (res.ticket?.showing_id && !showingId) {
        setShowingId(String(res.ticket.showing_id));
      }
    } catch (e) {
      setError(e.message);
    }
  }

  async function startCamera() {
    setError("");
    setCameraMsg("");
    setResult(null);
    if (!("BarcodeDetector" in window)) {
      setCameraMsg("Camera opened, but this browser needs manual code entry.");
    } else {
      detectorRef.current = new window.BarcodeDetector({ formats: ["qr_code"] });
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } },
        audio: false,
      });
      streamRef.current = stream;
      videoRef.current.srcObject = stream;
      await videoRef.current.play();
      setScannerOn(true);
      scanLoop();
    } catch (e) {
      setCameraMsg(e.message || "Camera access was blocked.");
    }
  }

  function stopCamera() {
    scanningRef.current = false;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setScannerOn(false);
  }

  async function scanLoop() {
    if (!detectorRef.current || !videoRef.current) return;
    scanningRef.current = true;
    while (scanningRef.current) {
      try {
        const codes = await detectorRef.current.detect(videoRef.current);
        const value = codes[0]?.rawValue;
        if (value && value !== lastCodeRef.current) {
          lastCodeRef.current = value;
          await validate(value);
          window.setTimeout(() => {
            lastCodeRef.current = "";
          }, 2500);
        }
      } catch {
        setCameraMsg("Scanning paused. Try manual entry or reload the camera.");
        scanningRef.current = false;
      }
      await new Promise((resolve) => window.setTimeout(resolve, 350));
    }
  }

  const scanned = tickets.filter((t) => t.scanned_at).length;

  return (
    <>
      <div className="spread scanner-head">
        <div>
          <h2 style={{ margin: 0 }}>Ticket Scan</h2>
          <div className="muted">Validate tickets and track attendance by showing.</div>
        </div>
        <div className="badge">{scanned}/{tickets.length} scanned</div>
      </div>

      {error && <p className="error">{error}</p>}

      <div className="scanner-grid">
        <div className="card scanner-panel">
          <div className="stack">
            <div>
              <div className="muted">Showing</div>
              <select
                style={{ width: "100%" }}
                value={showingId}
                onChange={(e) => setShowingId(e.target.value)}
              >
                <option value="">Accept any showing</option>
                {showings.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.title} - {new Date(s.scheduled_start).toLocaleString()}
                  </option>
                ))}
              </select>
            </div>

            <div className="camera-box">
              <video ref={videoRef} className="camera-video" playsInline muted />
              {!scannerOn && <div className="camera-empty">Camera idle</div>}
            </div>

            {cameraMsg && <p className="muted">{cameraMsg}</p>}

            <div className="row">
              <button className="btn" onClick={scannerOn ? stopCamera : startCamera}>
                {scannerOn ? "Stop Camera" : "Start Camera"}
              </button>
            </div>

            <div>
              <div className="muted">Manual code</div>
              <div className="row manual-scan">
                <input
                  value={manualCode}
                  onChange={(e) => setManualCode(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") validate(manualCode);
                  }}
                  placeholder="HTM-TICKET code"
                />
                <button className="btn secondary" onClick={() => validate(manualCode)}>
                  Validate
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className="card scanner-panel">
          <div className="stack">
            {result ? (
              <div className={statusClass(result.status)}>
                <b>{result.message}</b>
                {result.ticket && (
                  <div>
                    Ticket #{result.ticket.id} - Seat {result.ticket.seat || "-"} -{" "}
                    {result.ticket.name || "Guest"}
                  </div>
                )}
                {result.showing && (
                  <div className="muted">
                    {result.showing.title} - {new Date(result.showing.scheduled_start).toLocaleString()}
                  </div>
                )}
              </div>
            ) : (
              <div className="scan-result muted">No scan yet</div>
            )}

            <div>
              <div className="muted">Showing management</div>
              {selectedShowing ? (
                <div className="showing-summary">
                  <b>{selectedShowing.title || "(untitled)"}</b>
                  <span>{new Date(selectedShowing.scheduled_start).toLocaleString()}</span>
                  <span>{selectedShowing.computed_runtime_min} min</span>
                  <span>Status: {selectedShowing.status}</span>
                </div>
              ) : (
                <p className="muted">Select a showing to view its ticket manifest.</p>
              )}
            </div>

            <table>
              <thead>
                <tr>
                  <th>Ticket</th>
                  <th>Seat</th>
                  <th>Name</th>
                  <th>Scan status</th>
                </tr>
              </thead>
              <tbody>
                {tickets.map((t) => (
                  <tr key={t.id}>
                    <td>#{t.id}</td>
                    <td>{t.seat || "-"}</td>
                    <td>{t.name || "-"}</td>
                    <td className={t.scanned_at ? "ok" : "muted"}>{fmtDate(t.scanned_at)}</td>
                  </tr>
                ))}
                {showingId && tickets.length === 0 && (
                  <tr>
                    <td colSpan="4" className="muted">No tickets for this showing.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  );
}
