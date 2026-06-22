"""Settings endpoints: output routing, available devices, detected hardware."""
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import get_settings as get_app_settings
from ..database import get_db
from ..schemas import OutputsOut, SettingsOut, SettingsUpdate
from ..services import playback_client
from ..services.playback_client import PlaybackUnavailable
from ..services.settings_store import get_settings_row

router = APIRouter(prefix="/api/settings", tags=["settings"])
app_settings = get_app_settings()


@router.get("", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db)):
    return get_settings_row(db)


@router.put("", response_model=SettingsOut)
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    row = get_settings_row(db)
    if body.video_output_ids is not None:
        row.video_output_ids = body.video_output_ids
    if body.audio_output_id is not None:
        row.audio_output_id = body.audio_output_id or None
    if body.audio_mode is not None:
        if body.audio_mode not in ("passthrough", "pcm"):
            raise HTTPException(422, "audio_mode must be 'passthrough' or 'pcm'")
        row.audio_mode = body.audio_mode
    db.commit()
    db.refresh(row)
    return row


@router.get("/outputs", response_model=OutputsOut)
def list_outputs():
    """Discover available outputs from the playback service (SDI + GPU + audio)."""
    try:
        return playback_client.outputs()
    except PlaybackUnavailable as e:
        raise HTTPException(503, f"playback service unavailable: {e}")


@router.get("/hardware")
def detected_hardware():
    """Hardware found by deploy/discover.sh (GPUs, DeckLink, printers, audio)."""
    path = Path(app_settings.hardware_file)
    if not path.exists():
        return {"available": False}
    try:
        data = json.loads(path.read_text())
        data["available"] = True
        return data
    except (OSError, json.JSONDecodeError):
        return {"available": False}
