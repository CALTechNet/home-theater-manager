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
    outputs: dict | None = None


class ConfigureRequest(BaseModel):
    outputs: dict


# Simulated hardware outputs. The real Phase 3 service will enumerate these from
# the DeckLink SDK and the GPU (DRM/NVML).
VIDEO_OUTPUTS = [
    {"id": "decklink:0", "name": "Blackmagic DeckLink SDI", "type": "sdi"},
    {"id": "gpu:hdmi-0", "name": "GPU HDMI-0", "type": "hdmi"},
    {"id": "gpu:dp-0", "name": "GPU DisplayPort-0", "type": "displayport"},
]
AUDIO_OUTPUTS = [
    {"id": "sdi-embedded", "name": "SDI embedded audio (DeckLink)", "type": "sdi"},
    {"id": "hdmi-0", "name": "GPU HDMI-0 audio", "type": "hdmi"},
    {"id": "spdif-0", "name": "S/PDIF optical", "type": "spdif"},
]


class _State:
    """Thread-safe playback state with a simulated clock."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.state = "IDLE"          # IDLE|LOADED|PLAYING|PAUSED
        self.showing_id: int | None = None
        self.items: list[dict] = []
        self.outputs: dict | None = None
        self.idle_screen: dict = {"mode": "black", "logo_path": None, "scale": "fit"}
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
                "outputs": self.outputs,
                "idle_screen": self.idle_screen,
            }


_st = _State()


@app.post("/playback/load")
def load(req: LoadRequest):
    with _st.lock:
        _st.reset()
        _st.showing_id = req.showing_id
        _st.items = req.items
        _st.outputs = req.outputs
        if req.outputs and req.outputs.get("idle_screen"):
            _st.idle_screen = req.outputs["idle_screen"]
        _st.state = "LOADED"
    return _st.snapshot()


@app.post("/playback/configure")
def configure(req: ConfigureRequest):
    with _st.lock:
        _st.outputs = req.outputs
        _st.idle_screen = req.outputs.get(
            "idle_screen",
            {"mode": "black", "logo_path": None, "scale": "fit"},
        )
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
        outputs = _st.outputs
        idle_screen = _st.idle_screen
        _st.reset()
        _st.outputs = outputs
        _st.idle_screen = idle_screen
    snap = _st.snapshot()
    snap["showing_id"] = prior  # report which showing was ended
    return snap


@app.get("/playback/state")
def state():
    return _st.snapshot()


@app.get("/outputs")
def outputs():
    return {"video": VIDEO_OUTPUTS, "audio": AUDIO_OUTPUTS}


@app.get("/health")
def health():
    return {"status": "ok"}
