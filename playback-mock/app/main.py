"""Playback control service.

By default this runs the Phase 1 in-memory simulator. Set
`HTM_PLAYBACK_DRIVER=ffmpeg` on the host playback service to run real ffmpeg
processes while preserving the same control API.
"""
from fastapi import FastAPI
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


@app.get("/outputs")
def outputs():
    return player.outputs()


@app.get("/health")
def health():
    return {"status": "ok"}
