"""Global app settings (singleton) — output routing for video/audio."""
from sqlalchemy.orm import Session

from ..models import AppSettings
from .video_profiles import (
    default_tone_mapping,
    default_video_mode,
    effective_output_profile,
    normalize_tone_mapping,
    normalize_video_mode,
    profile_for,
)

SINGLETON_ID = 1


def get_settings_row(db: Session) -> AppSettings:
    row = db.get(AppSettings, SINGLETON_ID)
    if row is None:
        row = AppSettings(id=SINGLETON_ID, video_output_ids=[], audio_output_id=None,
                          audio_mode="passthrough", idle_screen_mode="black",
                          idle_logo_path=None, idle_logo_scale="fit",
                          tone_mapping=default_tone_mapping(),
                          video_mode=default_video_mode())
        db.add(row)
        db.commit()
        db.refresh(row)
    changed = False
    tone_mapping = normalize_tone_mapping(row.tone_mapping)
    if row.tone_mapping != tone_mapping:
        row.tone_mapping = tone_mapping
        changed = True
    video_mode = normalize_video_mode(row.video_mode)
    if row.video_mode != video_mode:
        row.video_mode = video_mode
        changed = True
    if changed:
        db.commit()
        db.refresh(row)
    return row


def output_payload(db: Session) -> dict:
    """Output routing to hand to the playback service on load."""
    row = get_settings_row(db)
    idle_mode = row.idle_screen_mode if row.idle_logo_path else "black"
    tone_mapping = normalize_tone_mapping(row.tone_mapping)
    video_mode = normalize_video_mode(row.video_mode)
    return {
        "video_outputs": row.video_output_ids or [],
        "audio_output": row.audio_output_id,
        "audio_mode": row.audio_mode,
        "tone_mapping": tone_mapping,
        "output_profile": effective_output_profile(tone_mapping),
        "video_mode": video_mode,
        "base_output_profile": profile_for(video_mode.get("base_output_profile_id")),
        "idle_screen": {
            "mode": idle_mode,
            "logo_path": row.idle_logo_path if idle_mode == "logo" else None,
            "scale": row.idle_logo_scale,
        },
    }
