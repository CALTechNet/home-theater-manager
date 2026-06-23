"""APScheduler integration: fire playback at each showing's scheduled start.

At a showing's start time, we load its playlist into the playback service and
start it (ARCHITECTURE.md §6.4). Manual shuttle controls can override anytime.
"""
import logging
import os
from datetime import datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.background import BackgroundScheduler

from ..config import get_settings
from ..database import SessionLocal
from ..models import Showing
from . import playback_client
from .settings_store import output_payload
from .showings import build_playlist_payload

log = logging.getLogger("htm.scheduler")
_scheduler: BackgroundScheduler | None = None

JOB_PREFIX = "showing-"
RECONCILE_JOB_ID = "reconcile-showings"
RECONCILE_INTERVAL_S = 30
# A scheduled show is started if "now" is within [start, start + window). The
# window is the show's runtime (so we never start one that would already be
# over), with a floor so zero-length/edge cases still catch up.
RECONCILE_GRACE_MIN = 5


def _job_id(showing_id: int) -> str:
    return f"{JOB_PREFIX}{showing_id}"


def _resolve_timezone() -> tzinfo:
    """The timezone scheduled_start values are expressed in.

    Showtimes are stored as naive local wall-clock times, so the scheduler must
    localize them in the operator's zone — otherwise a containerized backend
    (UTC by default) fires jobs at the wrong absolute time. Order: HTM_TIMEZONE,
    then the TZ env var, then the system local timezone, then UTC.
    """
    name = (get_settings().timezone or os.getenv("TZ") or "").strip()
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            log.warning("Unknown timezone %r; falling back to system local time", name)
    try:
        from tzlocal import get_localzone

        return get_localzone()
    except Exception:  # noqa: BLE001 - last resort so the app still starts
        log.warning("Could not determine local timezone; using UTC (showtimes may be off)")
        return ZoneInfo("UTC")


def _now_local() -> datetime:
    """Current wall-clock time as a naive datetime in the scheduler timezone, to
    compare against the naive local scheduled_start values stored in the DB."""
    tz = _scheduler.timezone if _scheduler is not None else _resolve_timezone()
    return datetime.now(tz).replace(tzinfo=None)


def _fire_showing(showing_id: int) -> None:
    """Load + start a showing's playlist. Runs in a scheduler thread.

    Idempotent: it only starts a showing that is still ``scheduled`` and claims
    it (``scheduled`` -> ``playing``) before contacting playback, so the one-shot
    date job and the reconcile loop can never double-start the same show. If
    playback fails it reverts to ``scheduled`` so the reconcile loop retries.
    """
    db = SessionLocal()
    try:
        showing = db.get(Showing, showing_id)
        if not showing or showing.status != "scheduled":
            return
        showing.status = "playing"  # claim
        db.commit()
        try:
            items = build_playlist_payload(showing)
            playback_client.load(showing.id, items, output_payload(db))
            playback_client.start()
            log.info("Started showing %s: %s", showing.id, showing.title)
        except Exception:  # noqa: BLE001 - revert so the reconcile loop retries
            log.exception("Failed to start showing %s; will retry", showing_id)
            showing.status = "scheduled"
            db.commit()
    except Exception:  # noqa: BLE001 - never let a job crash the scheduler
        log.exception("Failed to fire showing %s", showing_id)
    finally:
        db.close()


def _reconcile() -> None:
    """Safety net: start any scheduled showing whose time has arrived.

    Catches showings the one-shot date job missed — moved/rescheduled shows,
    fires missed during a restart, and retries after transient playback outages.
    """
    if _scheduler is None:
        return
    db = SessionLocal()
    try:
        now_local = _now_local()
        due = (
            db.query(Showing)
            .filter(Showing.status == "scheduled", Showing.scheduled_start <= now_local)
            .all()
        )
        for showing in due:
            window = max(showing.computed_runtime_min or 0, RECONCILE_GRACE_MIN)
            if showing.scheduled_start + timedelta(minutes=window) <= now_local:
                continue  # its run window has fully passed; don't resurrect it
            log.info(
                "Reconcile: starting due showing %s (scheduled %s, now %s)",
                showing.id, showing.scheduled_start, now_local,
            )
            _fire_showing(showing.id)
    except Exception:  # noqa: BLE001 - never let the loop die
        log.exception("Scheduler reconcile failed")
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
    tz = _resolve_timezone()
    _scheduler = BackgroundScheduler(timezone=tz)
    log.info("Scheduler timezone: %s", tz)
    _scheduler.start()

    # Safety-net loop that starts due showings even if a date job was missed.
    _scheduler.add_job(
        _reconcile,
        trigger="interval",
        seconds=RECONCILE_INTERVAL_S,
        id=RECONCILE_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

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
