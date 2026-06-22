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


def _reserved_connectors() -> list[str]:
    """Connectors the host console claimed (deploy/console-routing.sh)."""
    path = Path(app_settings.console_file)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return [str(c) for c in data.get("reserved_connectors", [])]
    except (OSError, json.JSONDecodeError):
        return []


def _connector_matches_output(connector: str, dev: dict) -> bool:
    """Best-effort match between a DRM connector name (e.g. HDMI-A-1) and a
    playback output device. Output IDs are not yet 1:1 with DRM names (mock /
    pre-Phase-3), so we match on the device 'type' family by connector prefix.
    Advisory only — drives a warning, never a hard block.
    """
    fam = connector.split("-", 1)[0].lower()  # HDMI-A-1 -> hdmi, DP-1 -> dp
    aliases = {
        "hdmi": {"hdmi"},
        "dp": {"displayport", "dp"},
        "vga": {"vga", "analog"},
        "edp": {"edp", "hdmi", "displayport"},
    }.get(fam, {fam})
    return dev.get("type", "").lower() in aliases


def _annotate_reserved(outputs: dict) -> dict:
    reserved = _reserved_connectors()
    if not reserved:
        return outputs
    for dev in outputs.get("video", []):
        hits = [c for c in reserved if _connector_matches_output(c, dev)]
        if hits:
            dev["reserved"] = True
            dev["reserved_reason"] = (
                f"Reserved for the host console ({', '.join(hits)}). "
                "Selecting it may conflict with local admin access."
            )
    return outputs


@router.get("/outputs", response_model=OutputsOut)
def list_outputs():
    """Discover available outputs from the playback service (SDI + GPU + audio).

    Video outputs are annotated `reserved` when deploy/console-routing.sh has
    claimed the matching connector for the host's Linux text console.
    """
    try:
        return _annotate_reserved(playback_client.outputs())
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
