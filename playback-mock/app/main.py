"""Mock playback service.

Implements the control API from ARCHITECTURE.md §6 with an in-memory state
machine and a simulated playback clock. Lets the entire management plane and UI
be exercised before the real host-side ffmpeg+DeckLink service exists.

The real Phase 3 service will expose the SAME API on the host.
"""
import threading
import time

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Playback Mock", version="0.1.0")


class LoadRequest(BaseModel):
    showing_id: int
    items: list[dict] = []


class _State:
    """Thread-safe playback state with a simulated clock."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.state = "IDLE"          # IDLE|LOADED|PLAYING|PAUSED
        self.showing_id: int | None = None
        self.items: list[dict] = []
        self.index = 0
        self.position = 0.0          # seconds into current item
        self._last_tick = time.monotonic()

    def _advance(self) -> None:
        """Advance the simulated clock if playing. Caller holds the lock."""
        now = time.monotonic()
        if self.state == "PLAYING":
            self.position += now - self._last_tick
        self._last_tick = now

    def snapshot(self) -> dict:
        with self.lock:
            self._advance()
            current = None
            if self.items and self.index < len(self.items):
                current = self.items[self.index].get("path")
            return {
                "state": self.state.lower(),
                "showing_id": self.showing_id,
                "position_seconds": round(self.position, 1),
                "current_item": current,
            }


_st = _State()


@app.post("/playback/load")
def load(req: LoadRequest):
    with _st.lock:
        _st.reset()
        _st.showing_id = req.showing_id
        _st.items = req.items
        _st.state = "LOADED"
    return _st.snapshot()


@app.post("/playback/start")
def start():
    with _st.lock:
        if _st.state in ("LOADED", "PAUSED"):
            _st.state = "PLAYING"
            _st._last_tick = time.monotonic()
    return _st.snapshot()


@app.post("/playback/pause")
def pause():
    with _st.lock:
        _st._advance()
        if _st.state == "PLAYING":
            _st.state = "PAUSED"
    return _st.snapshot()


@app.post("/playback/resume")
def resume():
    with _st.lock:
        if _st.state == "PAUSED":
            _st.state = "PLAYING"
            _st._last_tick = time.monotonic()
    return _st.snapshot()


@app.post("/playback/stop")
def stop():
    prior = _st.showing_id
    with _st.lock:
        _st.reset()
    snap = _st.snapshot()
    snap["showing_id"] = prior  # report which showing was ended
    return snap


@app.get("/playback/state")
def state():
    return _st.snapshot()


@app.get("/health")
def health():
    return {"status": "ok"}
