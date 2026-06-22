"""Scan the media root and probe files with ffprobe."""
import json
import subprocess
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import MediaFile

settings = get_settings()

VIDEO_EXTS = {".mkv", ".mp4", ".mov", ".m4v", ".ts", ".webm", ".avi"}

# Transfer characteristics that indicate HDR10 (PQ / SMPTE 2084).
HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}


def _ffprobe(path: str) -> dict:
    """Return ffprobe JSON for a file, or {} on failure."""
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", path,
            ],
            capture_output=True, text=True, timeout=60, check=True,
        )
        return json.loads(out.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return {}


def _parse_fps(rate: str) -> float:
    try:
        num, den = rate.split("/")
        den_f = float(den)
        return round(float(num) / den_f, 3) if den_f else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe_metadata(path: str) -> dict:
    """Extract the fields we persist from an ffprobe result."""
    data = _ffprobe(path)
    meta = {
        "duration_seconds": 0.0, "width": 0, "height": 0, "fps": 0.0,
        "video_codec": "", "color_primaries": "", "transfer_characteristics": "",
        "is_hdr10": False, "audio_summary": "",
    }
    if not data:
        return meta

    fmt = data.get("format", {})
    try:
        meta["duration_seconds"] = float(fmt.get("duration", 0.0))
    except (TypeError, ValueError):
        pass

    audio_descr = []
    for stream in data.get("streams", []):
        codec_type = stream.get("codec_type")
        if codec_type == "video" and not meta["video_codec"]:
            meta["video_codec"] = stream.get("codec_name", "")
            meta["width"] = int(stream.get("width", 0) or 0)
            meta["height"] = int(stream.get("height", 0) or 0)
            meta["fps"] = _parse_fps(stream.get("avg_frame_rate", "0/0"))
            meta["color_primaries"] = stream.get("color_primaries", "") or ""
            transfer = stream.get("color_transfer", "") or ""
            meta["transfer_characteristics"] = transfer
            meta["is_hdr10"] = transfer in HDR_TRANSFERS
        elif codec_type == "audio":
            ch = stream.get("channels", "?")
            audio_descr.append(f"{stream.get('codec_name', '?')} {ch}ch")
    meta["audio_summary"] = ", ".join(audio_descr)
    return meta


def scan_library(db: Session) -> dict:
    """Walk media_root, probe new/changed files, upsert MediaFile rows."""
    root = Path(settings.media_root)
    scanned = added = updated = 0
    if not root.exists():
        return {"scanned": 0, "added": 0, "updated": 0}

    existing = {m.path: m for m in db.query(MediaFile).all()}

    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in VIDEO_EXTS:
            continue
        scanned += 1
        path_str = str(p)
        meta = probe_metadata(path_str)

        row = existing.get(path_str)
        if row is None:
            row = MediaFile(path=path_str, title=p.stem, kind="feature", **meta)
            db.add(row)
            added += 1
        else:
            for k, v in meta.items():
                setattr(row, k, v)
            updated += 1

    db.commit()
    return {"scanned": scanned, "added": added, "updated": updated}
