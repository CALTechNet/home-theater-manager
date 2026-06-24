"""Showing helpers: playlist assembly and runtime computation."""
from pathlib import Path

from ..config import get_settings
from ..models import MediaFile, Showing, ShowingItem


def compute_runtime_min(items: list[ShowingItem]) -> int:
    """Total runtime of all playlist items, rounded to the nearest minute."""
    total_seconds = sum((it.media.duration_seconds or 0.0) for it in items if it.media)
    return round(total_seconds / 60)


def build_playlist_payload(showing: Showing) -> list[dict]:
    """Serialize a showing's ordered playlist for the playback control API."""
    settings = get_settings()
    return [
        {
            "path": _remap_media_path(
                it.media.path,
                settings.media_root,
                settings.playback_media_root or settings.media_root,
            ),
            "display_path": _remap_media_path(
                it.media.path,
                settings.media_root,
                settings.media_host_path or settings.media_root,
            ),
            "source_path": it.media.path,
            "role": it.role,
            "position": it.position,
            "is_hdr10": it.media.is_hdr10,
            "fps": it.media.fps,
            "width": it.media.width,
            "height": it.media.height,
            "color_primaries": it.media.color_primaries,
            "transfer_characteristics": it.media.transfer_characteristics,
        }
        for it in sorted(showing.items, key=lambda i: i.position)
        if it.media
    ]


def _remap_media_path(path: str, source_root: str, target_root: str) -> str:
    """Map a scanned backend media path to another root, preserving its relative path."""
    if not source_root or not target_root:
        return path
    try:
        rel = Path(path).relative_to(Path(source_root))
    except ValueError:
        return path
    return str(Path(target_root) / rel)


def replace_items(showing: Showing, item_specs: list[tuple[int, str]], media_by_id: dict[int, MediaFile]) -> None:
    """Rebuild a showing's playlist from (media_id, role) specs, in order.

    The operator's order is preserved so existing showings can be edited and
    reordered without the backend reshuffling the playlist.
    """
    showing.items.clear()

    feature_id = None
    for position, (media_id, role) in enumerate(item_specs):
        media = media_by_id.get(media_id)
        if media is None:
            continue
        if role == "feature" and feature_id is None:
            feature_id = media_id
        showing.items.append(
            ShowingItem(media_id=media_id, position=position, role=role, media=media)
        )

    # Keep feature_id in sync with the feature item, if any.
    if feature_id is not None:
        showing.feature_id = feature_id
