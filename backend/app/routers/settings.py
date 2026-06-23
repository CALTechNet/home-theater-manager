"""Settings endpoints: output routing, available devices, detected hardware."""
import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session
from PIL import Image, UnidentifiedImageError

from ..config import get_settings as get_app_settings
from ..database import get_db
from ..schemas import IdleLogoOut, OutputsOut, SettingsOut, SettingsUpdate
from ..services import playback_client
from ..services.playback_client import PlaybackUnavailable
from ..services.settings_store import get_settings_row, output_payload

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
    if body.idle_screen_mode is not None:
        if body.idle_screen_mode not in ("black", "logo"):
            raise HTTPException(422, "idle_screen_mode must be 'black' or 'logo'")
        row.idle_screen_mode = body.idle_screen_mode
    if body.idle_logo_scale is not None:
        if body.idle_logo_scale not in ("fit", "fill"):
            raise HTTPException(422, "idle_logo_scale must be 'fit' or 'fill'")
        row.idle_logo_scale = body.idle_logo_scale
    if body.time_format is not None:
        if body.time_format not in ("12h", "24h"):
            raise HTTPException(422, "time_format must be '12h' or '24h'")
        row.time_format = body.time_format
    db.commit()
    db.refresh(row)
    try:
        playback_client.configure(output_payload(db))
    except PlaybackUnavailable:
        pass
    return row


def _logo_dir() -> Path:
    path = Path(app_settings.runtime_dir) / "assets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _image_size(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as image:
            return image.size
    except (OSError, UnidentifiedImageError) as e:
        raise HTTPException(422, "idle logo must be a valid image") from e


@router.post("/idle-logo", response_model=IdleLogoOut)
async def upload_idle_logo(file: UploadFile = File(...), db: Session = Depends(get_db)):
    ext_by_type = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
    }
    ext = ext_by_type.get(file.content_type or "")
    if ext is None:
        raise HTTPException(422, "idle logo must be PNG, JPEG, or WebP")

    data = await file.read()
    if not data:
        raise HTTPException(422, "idle logo is empty")
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(413, "idle logo must be 25 MB or smaller")

    target = _logo_dir() / f"idle-logo{ext}"
    target.write_bytes(data)
    width, height = _image_size(target)
    if (width, height) != (3840, 2160):
        target.unlink(missing_ok=True)
        raise HTTPException(422, "idle logo must be exactly 3840x2160")

    row = get_settings_row(db)
    row.idle_logo_path = str(target)
    row.idle_screen_mode = "logo"
    db.commit()
    db.refresh(row)
    try:
        playback_client.configure(output_payload(db))
    except PlaybackUnavailable:
        pass
    return {"idle_logo_path": row.idle_logo_path, "width": width, "height": height}


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


def _hardware_connectors() -> list[dict]:
    path = Path(app_settings.hardware_file)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    connectors = data.get("connectors", [])
    return [c for c in connectors if isinstance(c, dict)] if isinstance(connectors, list) else []


def _annotate_display_connectors(outputs: dict) -> dict:
    """Attach DRM connector details from hardware discovery to GPU outputs."""
    connectors = _hardware_connectors()
    by_name = {str(c.get("name", "")): c for c in connectors if c.get("name")}
    for dev in outputs.get("video", []):
        connector = str(dev.get("drm_connector") or "")
        if not connector and str(dev.get("id", "")).startswith("gpu:"):
            connector = str(dev.get("id", "")).split(":", 1)[1]
        match = by_name.get(connector)
        if match:
            dev["drm_connector"] = connector
            dev["drm_device"] = dev.get("drm_device") or match.get("device")
            dev["status"] = match.get("status")
    return outputs


@router.get("/outputs", response_model=OutputsOut)
def list_outputs():
    """Discover available outputs from the playback service (SDI + GPU + audio).

    Video outputs are annotated `reserved` when deploy/console-routing.sh has
    claimed the matching connector for the host's Linux text console.
    """
    try:
        return _annotate_reserved(_annotate_display_connectors(playback_client.outputs()))
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
