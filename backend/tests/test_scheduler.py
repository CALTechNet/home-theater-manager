"""Scheduler timezone handling — scheduled showings must fire at the operator's
local wall-clock time even when the backend container runs in UTC.

Uses an isolated SQLite file (the scheduler module imports the DB layer).
"""
import os
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Configure an isolated DB before importing the app modules.
_tmp = tempfile.mkdtemp()
os.environ.setdefault("HTM_DATABASE_URL", f"sqlite:///{_tmp}/sched.db")
os.environ.setdefault("HTM_MEDIA_ROOT", _tmp)

from apscheduler.schedulers.background import BackgroundScheduler  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.models import Showing  # noqa: E402
from app.services import scheduler as sch  # noqa: E402


def _add_showing(start, status="scheduled", runtime=0):
    db = SessionLocal()
    try:
        s = Showing(title="T", scheduled_start=start, status=status, computed_runtime_min=runtime)
        db.add(s)
        db.commit()
        db.refresh(s)
        return s.id
    finally:
        db.close()


def _status(showing_id):
    db = SessionLocal()
    try:
        return db.get(Showing, showing_id).status
    finally:
        db.close()


def test_resolve_timezone_prefers_setting(monkeypatch):
    monkeypatch.setenv("HTM_TIMEZONE", "America/Chicago")
    get_settings.cache_clear()
    try:
        assert str(sch._resolve_timezone()) == "America/Chicago"
    finally:
        get_settings.cache_clear()


def test_resolve_timezone_falls_back_to_tz_env(monkeypatch):
    monkeypatch.delenv("HTM_TIMEZONE", raising=False)
    monkeypatch.setenv("TZ", "America/New_York")
    get_settings.cache_clear()
    try:
        assert str(sch._resolve_timezone()) == "America/New_York"
    finally:
        get_settings.cache_clear()


def test_resolve_timezone_ignores_bad_name(monkeypatch):
    monkeypatch.setenv("HTM_TIMEZONE", "Not/AZone")
    monkeypatch.delenv("TZ", raising=False)
    get_settings.cache_clear()
    try:
        # Falls through to the system local zone (tzlocal) without raising.
        assert sch._resolve_timezone() is not None
    finally:
        get_settings.cache_clear()


def test_naive_showtime_fires_at_local_wall_clock():
    """A naive scheduled_start scheduled under the operator's tz must resolve to
    that wall clock, not be misread as UTC (the bug)."""
    when = datetime(2099, 7, 1, 19, 0, 0)  # naive local "7pm"
    # An explicit, known zone keeps the assertion deterministic in CI. This is
    # the same wiring start_scheduler() uses: BackgroundScheduler(timezone=...).
    scheduler = BackgroundScheduler(timezone="America/Chicago")
    scheduler.start()
    try:
        job = scheduler.add_job(lambda: None, trigger="date", run_date=when, id="t")
        assert job.next_run_time == when.replace(tzinfo=ZoneInfo("America/Chicago"))
        # And it must NOT be the buggy UTC interpretation.
        assert job.next_run_time != when.replace(tzinfo=ZoneInfo("UTC"))
    finally:
        scheduler.shutdown(wait=False)


def test_reconcile_starts_due_scheduled_shows_only(monkeypatch):
    init_db()
    fired = []
    monkeypatch.setattr(sch, "_fire_showing", lambda sid: fired.append(sid))
    old = sch._scheduler
    sch._scheduler = BackgroundScheduler(timezone="America/Chicago")  # not started
    try:
        now = sch._now_local()
        due = _add_showing(now - timedelta(minutes=1), "scheduled", runtime=120)
        future = _add_showing(now + timedelta(hours=2), "scheduled", runtime=120)
        stale = _add_showing(now - timedelta(hours=5), "scheduled", runtime=120)  # window passed
        done = _add_showing(now - timedelta(minutes=1), "done", runtime=120)

        sch._reconcile()

        assert due in fired
        assert future not in fired   # not started yet
        assert stale not in fired    # run window fully passed
        assert done not in fired     # only "scheduled" shows are reconciled
    finally:
        sch._scheduler = old


def test_fire_showing_is_idempotent(monkeypatch):
    init_db()
    calls = []
    monkeypatch.setattr(sch, "output_payload", lambda db: {})
    monkeypatch.setattr(sch.playback_client, "load", lambda *a, **k: calls.append("load"))
    monkeypatch.setattr(sch.playback_client, "start", lambda *a, **k: calls.append("start"))

    sid = _add_showing(datetime(2099, 1, 1, 12, 0, 0), "scheduled", runtime=10)
    sch._fire_showing(sid)
    assert _status(sid) == "playing"
    assert calls == ["load", "start"]

    sch._fire_showing(sid)  # already playing -> no-op
    assert calls == ["load", "start"]


def test_fire_showing_reverts_on_playback_failure(monkeypatch):
    init_db()
    monkeypatch.setattr(sch, "output_payload", lambda db: {})
    monkeypatch.setattr(sch.playback_client, "load", lambda *a, **k: None)

    def _boom(*a, **k):
        raise RuntimeError("playback down")

    monkeypatch.setattr(sch.playback_client, "start", _boom)

    sid = _add_showing(datetime(2099, 1, 1, 12, 0, 0), "scheduled", runtime=10)
    sch._fire_showing(sid)
    assert _status(sid) == "scheduled"  # reverted so the reconcile loop retries
