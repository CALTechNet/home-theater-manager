"""Global app settings (singleton) — output routing for video/audio."""
from sqlalchemy.orm import Session

from ..models import AppSettings

SINGLETON_ID = 1


def get_settings_row(db: Session) -> AppSettings:
    row = db.get(AppSettings, SINGLETON_ID)
    if row is None:
        row = AppSettings(id=SINGLETON_ID, video_output_ids=[], audio_output_id=None,
                          audio_mode="passthrough")
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def output_payload(db: Session) -> dict:
    """Output routing to hand to the playback service on load."""
    row = get_settings_row(db)
    return {
        "video_outputs": row.video_output_ids or [],
        "audio_output": row.audio_output_id,
        "audio_mode": row.audio_mode,
    }
