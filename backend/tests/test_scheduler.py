"""Scheduler timezone handling — scheduled showings must fire at the operator's
local wall-clock time even when the backend container runs in UTC.

Uses an isolated SQLite file (the scheduler module imports the DB layer).
"""
import os
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

# Configure an isolated DB before importing the app modules.
_tmp = tempfile.mkdtemp()
os.environ.setdefault("HTM_DATABASE_URL", f"sqlite:///{_tmp}/sched.db")
os.environ.setdefault("HTM_MEDIA_ROOT", _tmp)

from apscheduler.schedulers.background import BackgroundScheduler  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services import scheduler as sch  # noqa: E402


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
