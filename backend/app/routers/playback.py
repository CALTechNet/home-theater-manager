"""Playback / shuttle control endpoints (Now Showing tab).

These proxy to the host playback service and keep Showing.status in sync.
"""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Showing
from ..schemas import PlaybackStateOut
from ..services import playback_client
from ..services.playback_client import PlaybackUnavailable
from ..services.settings_store import output_payload
from ..services.showings import build_playlist_payload

router = APIRouter(prefix="/api/playback", tags=["playback"])


def _state_from_dict(d: dict) -> PlaybackStateOut:
    return PlaybackStateOut(
        state=d.get("state", "unknown"),
        showing_id=d.get("showing_id"),
        position_seconds=d.get("position_seconds", 0.0),
        current_item=d.get("current_item"),
    )


@router.get("/state", response_model=PlaybackStateOut)
def get_state():
    try:
        return _state_from_dict(playback_client.state())
    except PlaybackUnavailable as e:
        raise HTTPException(503, f"playback service unavailable: {e}")


@router.get("/preview")
def preview():
    """Proxy a JPEG snapshot of the current output for the Now Showing preview."""
    try:
        result = playback_client.preview()
    except PlaybackUnavailable as e:
        raise HTTPException(503, f"playback service unavailable: {e}")
    if result is None:
        raise HTTPException(404, "no preview available")
    content, media_type = result
    return Response(content=content, media_type=media_type, headers={"Cache-Control": "no-store"})


@router.post("/start/{showing_id}", response_model=PlaybackStateOut)
def start_show(showing_id: int, db: Session = Depends(get_db)):
    """Start Show: load the showing's playlist and begin immediately."""
    showing = db.get(Showing, showing_id)
    if showing is None:
        raise HTTPException(404, "showing not found")
    try:
        playback_client.load(showing.id, build_playlist_payload(showing), output_payload(db))
        result = playback_client.start()
    except PlaybackUnavailable as e:
        raise HTTPException(503, f"playback service unavailable: {e}")
    showing.status = "playing"
    db.commit()
    return _state_from_dict(result)


@router.post("/pause", response_model=PlaybackStateOut)
def pause(db: Session = Depends(get_db)):
    try:
        result = playback_client.pause()
    except PlaybackUnavailable as e:
        raise HTTPException(503, f"playback service unavailable: {e}")
    _sync_status(db, result)
    return _state_from_dict(result)


@router.post("/resume", response_model=PlaybackStateOut)
def resume(db: Session = Depends(get_db)):
    try:
        result = playback_client.resume()
    except PlaybackUnavailable as e:
        raise HTTPException(503, f"playback service unavailable: {e}")
    _sync_status(db, result)
    return _state_from_dict(result)


@router.post("/stop", response_model=PlaybackStateOut)
def stop_show(db: Session = Depends(get_db)):
    """End Show."""
    try:
        result = playback_client.stop()
    except PlaybackUnavailable as e:
        raise HTTPException(503, f"playback service unavailable: {e}")
    showing_id = result.get("showing_id")
    if showing_id:
        showing = db.get(Showing, showing_id)
        if showing:
            showing.status = "done"
            db.commit()
    return _state_from_dict(result)


def _sync_status(db: Session, result: dict) -> None:
    showing_id = result.get("showing_id")
    if not showing_id:
        return
    showing = db.get(Showing, showing_id)
    if not showing:
        return
    mapping = {"playing": "playing", "paused": "paused"}
    new_status = mapping.get(result.get("state", ""))
    if new_status:
        showing.status = new_status
        db.commit()
