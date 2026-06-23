"""Showing helpers: playlist assembly and runtime computation."""
from ..models import MediaFile, Showing, ShowingItem


def compute_runtime_min(items: list[ShowingItem]) -> int:
    """Total runtime of all playlist items, rounded to the nearest minute."""
    total_seconds = sum((it.media.duration_seconds or 0.0) for it in items if it.media)
    return round(total_seconds / 60)


def build_playlist_payload(showing: Showing) -> list[dict]:
    """Serialize a showing's ordered playlist for the playback control API."""
    return [
        {
            "path": it.media.path,
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


def replace_items(showing: Showing, item_specs: list[tuple[int, str]], media_by_id: dict[int, MediaFile]) -> None:
    """Rebuild a showing's playlist from (media_id, role) specs, in order.

    Trailers keep the given order; the feature is forced to the end so the
    schedule/runtime reflects "trailers then feature".
    """
    showing.items.clear()

    trailers = [(mid, role) for mid, role in item_specs if role != "feature"]
    features = [(mid, role) for mid, role in item_specs if role == "feature"]
    ordered = trailers + features

    for position, (media_id, role) in enumerate(ordered):
        media = media_by_id.get(media_id)
        if media is None:
            continue
        showing.items.append(
            ShowingItem(media_id=media_id, position=position, role=role, media=media)
        )

    # Keep feature_id in sync with the feature item, if any.
    if features:
        showing.feature_id = features[0][0]
