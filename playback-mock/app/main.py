"""Playback control service.

By default this runs the Phase 1 in-memory simulator. Set
`HTM_PLAYBACK_DRIVER=ffmpeg` on the host playback service to run real ffmpeg
processes while preserving the same control API.
"""
import os
import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from .player import create_player

app = FastAPI(title="Home Theater Playback", version="0.2.0")
player = create_player()


class LoadRequest(BaseModel):
    showing_id: int
    items: list[dict] = []
    outputs: dict | None = None


class ConfigureRequest(BaseModel):
    outputs: dict


@app.post("/playback/load")
def load(req: LoadRequest):
    return player.load(req.showing_id, req.items, req.outputs)


@app.post("/playback/configure")
def configure(req: ConfigureRequest):
    return player.configure(req.outputs)


@app.post("/playback/start")
def start():
    return player.start()


@app.post("/playback/pause")
def pause():
    return player.pause()


@app.post("/playback/resume")
def resume():
    return player.resume()


@app.post("/playback/stop")
def stop():
    return player.stop()


@app.get("/playback/state")
def state():
    return player.snapshot()


def _grab_frame(path: str, position: float = 0.0) -> bytes | None:
    """Extract one downscaled JPEG frame from a media file (or image) via ffmpeg."""
    ffmpeg = os.getenv("HTM_FFMPEG_BIN", "ffmpeg")
    try:
        out = subprocess.run(
            [
                ffmpeg, "-nostdin", "-loglevel", "error",
                "-ss", str(max(position, 0.0)), "-i", path,
                "-frames:v", "1", "-vf", "scale=640:-2", "-f", "mjpeg", "-",
            ],
            capture_output=True, timeout=15, check=True,
        )
        return out.stdout or None
    except (subprocess.SubprocessError, OSError):
        return None


@app.get("/preview")
def preview():
    """A JPEG shot of what's currently on the output: the current frame while
    playing, else the idle logo when one is configured."""
    snap = player.snapshot()
    path = snap.get("current_item")
    if snap.get("state") in ("playing", "paused") and path:
        frame = _grab_frame(path, snap.get("position_seconds", 0.0))
        if frame:
            return Response(content=frame, media_type="image/jpeg")
    idle = snap.get("idle_screen") or {}
    logo = idle.get("logo_path")
    if idle.get("mode") == "logo" and logo and Path(str(logo)).exists():
        frame = _grab_frame(str(logo), 0.0)
        if frame:
            return Response(content=frame, media_type="image/jpeg")
    raise HTTPException(404, "no preview available")


@app.get("/outputs")
def outputs():
    return player.outputs()


@app.get("/health")
def health():
    return {"status": "ok"}
