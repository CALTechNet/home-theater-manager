"""Verify the additive migrator adds new columns to a stale database."""
import os
import tempfile

os.environ.setdefault("HTM_DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine, inspect, text  # noqa: E402

from app.migrations import run_migrations  # noqa: E402


def test_adds_missing_columns():
    tmp = tempfile.mkdtemp()
    eng = create_engine(f"sqlite:///{tmp}/stale.db")

    # Simulate an OLD schema: media_files predating the rich-metadata columns.
    with eng.begin() as conn:
        conn.execute(text(
            "CREATE TABLE media_files ("
            "id INTEGER PRIMARY KEY, path VARCHAR, kind VARCHAR, title VARCHAR)"
        ))

    applied = run_migrations(eng)

    cols = {c["name"] for c in inspect(eng).get_columns("media_files")}
    # Newer columns must have been added.
    for c in ("aspect_ratio", "bitrate", "file_size", "audio_format", "is_hdr10"):
        assert c in cols, f"{c} missing after migration"
    assert any("media_files." in a for a in applied)

    # New tables created too.
    assert "app_settings" in inspect(eng).get_table_names()

    # Idempotent: a second run applies nothing.
    assert run_migrations(eng) == []


def test_adds_new_app_settings_json_columns():
    tmp = tempfile.mkdtemp()
    eng = create_engine(f"sqlite:///{tmp}/settings-stale.db")

    with eng.begin() as conn:
        conn.execute(text(
            "CREATE TABLE app_settings ("
            "id INTEGER PRIMARY KEY, "
            "video_output_ids JSON, "
            "audio_output_id VARCHAR, "
            "audio_mode VARCHAR, "
            "idle_screen_mode VARCHAR, "
            "idle_logo_path VARCHAR, "
            "idle_logo_scale VARCHAR, "
            "time_format VARCHAR, "
            "updated_at DATETIME)"
        ))

    applied = run_migrations(eng)

    cols = {c["name"] for c in inspect(eng).get_columns("app_settings")}
    assert "tone_mapping" in cols
    assert "video_mode" in cols
    assert "app_settings.tone_mapping" in applied
    assert "app_settings.video_mode" in applied
