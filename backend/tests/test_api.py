"""Phase 1 smoke + logic tests. Run: pytest (from backend/).

Uses an isolated SQLite file and a fake playback service so no hardware or
network is required.
"""
import os
import tempfile

import pytest

# Configure an isolated DB before importing the app.
_tmp = tempfile.mkdtemp()
os.environ["HTM_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["HTM_MEDIA_ROOT"] = _tmp

from fastapi.testclient import TestClient  # noqa: E402

from app.database import init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import MediaFile, ShowingItem  # noqa: E402
from app.services.showings import compute_runtime_min  # noqa: E402


@pytest.fixture(scope="module")
def client():
    init_db()
    with TestClient(app) as c:
        yield c


def _make_media(client, db_kind="feature", duration=5400.0):
    """Insert a MediaFile directly (bypassing the scanner)."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        m = MediaFile(path=f"/tmp/{db_kind}_{duration}.mkv", title="X",
                      kind=db_kind, duration_seconds=duration)
        db.add(m)
        db.commit()
        db.refresh(m)
        return m.id
    finally:
        db.close()


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_runtime_rounding():
    # 5400s feature + 150s trailer = 5550s -> 92.5 min -> rounds to 92.
    items = [
        ShowingItem(role="trailer", media=MediaFile(duration_seconds=150.0)),
        ShowingItem(role="feature", media=MediaFile(duration_seconds=5400.0)),
    ]
    assert compute_runtime_min(items) == 92


def test_create_showing_computes_runtime(client):
    feature = _make_media(client, "feature", duration=5400.0)  # 90 min
    trailer = _make_media(client, "trailer", duration=150.0)   # 2.5 min
    r = client.post("/api/showings", json={
        "title": "Test Film",
        "scheduled_start": "2026-07-01T19:00:00",
        "items": [
            {"media_id": trailer, "role": "trailer"},
            {"media_id": feature, "role": "feature"},
        ],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["computed_runtime_min"] == 92
    # Feature is forced to the end of the playlist.
    assert body["items"][-1]["role"] == "feature"


def test_ticket_copy_index_and_pdf(client):
    feature = _make_media(client, "feature", duration=3600.0)
    s = client.post("/api/showings", json={
        "title": "Ticket Film",
        "scheduled_start": "2026-07-02T20:00:00",
        "feature_id": feature,
    }).json()

    payload = {"showing_id": s["id"], "seat": "3C", "name": "Ada",
               "incl_popcorn": True}
    r1 = client.post("/api/tickets", json=payload)
    r2 = client.post("/api/tickets", json=payload)
    assert r1.status_code == 201
    assert r1.json()["copy_index"] == 1
    assert r2.json()["copy_index"] == 2

    ticket_id = r1.json()["id"]
    # Both PDF styles render and return a valid PDF.
    for style in ("receipt", "fullpage"):
        pdf = client.get(f"/api/tickets/{ticket_id}/pdf?style={style}")
        assert pdf.status_code == 200
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.content[:4] == b"%PDF"
    # Invalid style is rejected.
    assert client.get(f"/api/tickets/{ticket_id}/pdf?style=bogus").status_code == 422


def test_seat_grid(client):
    grid = client.get("/api/tickets/seat-grid").json()
    assert grid["rows"] == ["A", "B", "C", "D", "E", "F"]
    assert grid["numbers"] == [1, 2, 3, 4, 5, 6]


def test_settings_defaults_and_update(client):
    s = client.get("/api/settings").json()
    assert s["video_output_ids"] == []
    assert s["audio_mode"] == "passthrough"

    r = client.put("/api/settings", json={
        "video_output_ids": ["decklink:0", "gpu:hdmi-0"],
        "audio_output_id": "sdi-embedded",
        "audio_mode": "pcm",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["video_output_ids"] == ["decklink:0", "gpu:hdmi-0"]
    assert body["audio_output_id"] == "sdi-embedded"
    assert body["audio_mode"] == "pcm"

    # rejects invalid audio mode
    assert client.put("/api/settings", json={"audio_mode": "bogus"}).status_code == 422


def test_audio_format_detection():
    from app.services.media_scan import _aspect_ratio, _audio_format

    atmos = _audio_format({"codec_name": "truehd", "profile": "",
                           "channel_layout": "7.1", "channels": 8,
                           "tags": {"title": "TrueHD Atmos 7.1"}})
    assert "Atmos" in atmos

    dtsx = _audio_format({"codec_name": "dts", "profile": "DTS-HD MA + DTS:X",
                          "channels": 8, "channel_layout": "7.1"})
    assert dtsx == "DTS:X"

    ddp = _audio_format({"codec_name": "eac3", "profile": "", "channels": 6,
                         "channel_layout": "5.1"})
    assert ddp == "Dolby Digital+ 5.1"

    assert _aspect_ratio({"display_aspect_ratio": "0:1"}, 3840, 2160) == "16:9"
    assert _aspect_ratio({}, 3840, 1600) == "2.40:1"
