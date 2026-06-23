"""Global app settings (singleton) — output routing for video/audio."""
from sqlalchemy.orm import Session

from ..models import AppSettings

SINGLETON_ID = 1


def get_settings_row(db: Session) -> AppSettings:
    row = db.get(AppSettings, SINGLETON_ID)
    if row is None:
        row = AppSettings(id=SINGLETON_ID, video_output_ids=[], audio_output_id=None,
                          audio_mode="passthrough", idle_screen_mode="black",
                          idle_logo_path=None, idle_logo_scale="fit")
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def output_payload(db: Session) -> dict:
    """Output routing to hand to the playback service on load."""
    row = get_settings_row(db)
    idle_mode = row.idle_screen_mode if row.idle_logo_path else "black"
    return {
        "video_outputs": row.video_output_ids or [],
        "audio_output": row.audio_output_id,
        "audio_mode": row.audio_mode,
        "idle_screen": {
            "mode": idle_mode,
            "logo_path": row.idle_logo_path if idle_mode == "logo" else None,
            "scale": row.idle_logo_scale,
        },
    }
