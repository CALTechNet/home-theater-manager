"""Scan the media root and probe files with ffprobe."""
import json
import subprocess
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import MediaFile

settings = get_settings()

VIDEO_EXTS = {
    ".3g2",
    ".3gp",
    ".avi",
    ".divx",
    ".f4v",
    ".flv",
    ".m2ts",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".mts",
    ".ogv",
    ".ts",
    ".vob",
    ".webm",
    ".wmv",
}

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


def _aspect_ratio(stream: dict, width: int, height: int) -> str:
    """Friendly display aspect ratio, e.g. '2.39:1' or '16:9'."""
    dar = stream.get("display_aspect_ratio", "")
    if dar and ":" in dar and dar != "0:1":
        try:
            a, b = (float(x) for x in dar.split(":"))
            if b:
                ratio = a / b
                # Keep clean labels for the common 4:3 / 16:9 cases.
                if abs(ratio - 4 / 3) < 0.02:
                    return "4:3"
                if abs(ratio - 16 / 9) < 0.02:
                    return "16:9"
                return f"{ratio:.2f}:1"
        except ValueError:
            pass
    if width and height:
        ratio = width / height
        if abs(ratio - 4 / 3) < 0.02:
            return "4:3"
        if abs(ratio - 16 / 9) < 0.02:
            return "16:9"
        return f"{ratio:.2f}:1"
    return ""


def _channel_label(channels: int, layout: str) -> str:
    if layout and layout not in ("unknown",):
        return layout
    return {1: "mono", 2: "2.0", 6: "5.1", 8: "7.1"}.get(channels, f"{channels}ch" if channels else "")


def _audio_format(stream: dict) -> str:
    """Best-effort human label including Atmos / DTS:X detection."""
    codec = (stream.get("codec_name") or "").lower()
    profile = (stream.get("profile") or "")
    layout = stream.get("channel_layout", "") or ""
    channels = int(stream.get("channels", 0) or 0)
    tags = stream.get("tags", {}) or {}
    blob = f"{codec} {profile} {layout} {tags}".lower()
    ch = _channel_label(channels, layout)

    if "atmos" in blob or "joc" in blob:
        base = "TrueHD" if codec == "truehd" else ("E-AC3" if codec == "eac3" else codec.upper())
        return f"Dolby Atmos ({base})"
    if "dts:x" in blob or "dts-x" in blob or "dtsx" in blob:
        return "DTS:X"

    names = {
        "truehd": "Dolby TrueHD",
        "eac3": "Dolby Digital+",
        "ac3": "Dolby Digital",
        "aac": "AAC",
        "opus": "Opus",
        "flac": "FLAC",
        "mp3": "MP3",
    }
    if codec == "dts":
        base = "DTS-HD MA" if "ma" in profile.lower() else ("DTS-HD HRA" if "hra" in profile.lower() else "DTS")
        return f"{base} {ch}".strip()
    if codec.startswith("pcm"):
        return f"PCM {ch}".strip()
    label = names.get(codec, codec.upper())
    return f"{label} {ch}".strip()


def probe_metadata(path: str) -> dict:
    """Extract the fields we persist from an ffprobe result."""
    data = _ffprobe(path)
    meta = {
        "duration_seconds": 0.0, "width": 0, "height": 0, "fps": 0.0,
        "video_codec": "", "color_primaries": "", "transfer_characteristics": "",
        "is_hdr10": False, "aspect_ratio": "", "file_size": 0, "bitrate": 0,
        "audio_codec": "", "audio_profile": "", "audio_channels": 0,
        "audio_channel_layout": "", "audio_format": "", "audio_summary": "",
    }
    if not data:
        return meta

    fmt = data.get("format", {})
    try:
        meta["duration_seconds"] = float(fmt.get("duration", 0.0))
    except (TypeError, ValueError):
        pass
    try:
        meta["file_size"] = int(fmt.get("size", 0) or 0)
    except (TypeError, ValueError):
        pass
    try:
        meta["bitrate"] = int(fmt.get("bit_rate", 0) or 0)
    except (TypeError, ValueError):
        pass

    audio_descr = []
    first_audio = True
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
            meta["aspect_ratio"] = _aspect_ratio(stream, meta["width"], meta["height"])
        elif codec_type == "audio":
            label = _audio_format(stream)
            audio_descr.append(label)
            if first_audio:
                meta["audio_codec"] = stream.get("codec_name", "") or ""
                meta["audio_profile"] = stream.get("profile", "") or ""
                meta["audio_channels"] = int(stream.get("channels", 0) or 0)
                meta["audio_channel_layout"] = stream.get("channel_layout", "") or ""
                meta["audio_format"] = label
                first_audio = False
    meta["audio_summary"] = ", ".join(audio_descr)

    if not meta["file_size"]:
        try:
            meta["file_size"] = Path(path).stat().st_size
        except OSError:
            pass
    return meta


def _is_video_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTS


def scan_library(db: Session) -> dict:
    """Walk every folder in media_root, probe video files, upsert MediaFile rows."""
    root = Path(settings.media_root)
    scanned = added = updated = 0
    if not root.exists():
        return {"scanned": 0, "added": 0, "updated": 0}

    existing = {m.path: m for m in db.query(MediaFile).all()}

    for p in sorted(root.rglob("*")):
        if not _is_video_file(p):
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
