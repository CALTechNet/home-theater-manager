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
