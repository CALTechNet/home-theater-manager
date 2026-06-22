"""APScheduler integration: fire playback at each showing's scheduled start.

At a showing's start time, we load its playlist into the playback service and
start it (ARCHITECTURE.md §6.4). Manual shuttle controls can override anytime.
"""
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from ..database import SessionLocal
from ..models import Showing
from . import playback_client
from .showings import build_playlist_payload

log = logging.getLogger("htm.scheduler")
_scheduler: BackgroundScheduler | None = None

JOB_PREFIX = "showing-"


def _job_id(showing_id: int) -> str:
    return f"{JOB_PREFIX}{showing_id}"


def _fire_showing(showing_id: int) -> None:
    """Load + start a showing's playlist. Runs in a scheduler thread."""
    db = SessionLocal()
    try:
        showing = db.get(Showing, showing_id)
        if not showing or showing.status in ("canceled", "done"):
            return
        items = build_playlist_payload(showing)
        playback_client.load(showing.id, items)
        playback_client.start()
        showing.status = "playing"
        db.commit()
        log.info("Started showing %s: %s", showing.id, showing.title)
    except Exception:  # noqa: BLE001 - never let a job crash the scheduler
        log.exception("Failed to fire showing %s", showing_id)
    finally:
        db.close()


def schedule_showing(showing: Showing) -> None:
    if _scheduler is None:
        return
    _scheduler.add_job(
        _fire_showing,
        trigger="date",
        run_date=showing.scheduled_start,
        args=[showing.id],
        id=_job_id(showing.id),
        replace_existing=True,
        misfire_grace_time=300,
    )


def unschedule_showing(showing_id: int) -> None:
    if _scheduler is None:
        return
    try:
        _scheduler.remove_job(_job_id(showing_id))
    except Exception:  # noqa: BLE001 - job may not exist
        pass


def start_scheduler() -> None:
    """Start the scheduler and (re)register all future scheduled showings."""
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler()
    _scheduler.start()

    db = SessionLocal()
    try:
        for showing in db.query(Showing).filter(Showing.status == "scheduled").all():
            schedule_showing(showing)
    finally:
        db.close()


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
