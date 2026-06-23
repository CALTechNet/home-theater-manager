"""Phase 1 smoke + logic tests. Run: pytest (from backend/).

Uses an isolated SQLite file and a fake playback service so no hardware or
network is required.
"""
import os
import tempfile
from io import BytesIO

import pytest
from PIL import Image

# Configure an isolated DB before importing the app.
_tmp = tempfile.mkdtemp()
os.environ["HTM_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["HTM_MEDIA_ROOT"] = _tmp
os.environ["HTM_SEAT_MAX_ROW"] = "F"
os.environ["HTM_SEAT_MAX_NUMBER"] = "6"

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


def test_media_storage(client):
    # HTM_MEDIA_ROOT points at a real temp dir, so disk_usage resolves.
    r = client.get("/api/media/storage")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] > 0
    assert body["used"] + body["free"] <= body["total"]
    assert 0.0 <= body["percent_used"] <= 100.0


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


def test_delete_media(client):
    # A standalone media row can be removed.
    mid = _make_media(client, "trailer", duration=120.0)
    assert client.delete(f"/api/media/{mid}").status_code == 204
    assert client.delete(f"/api/media/{mid}").status_code == 404  # gone


def test_delete_media_blocked_when_in_showing(client):
    feature = _make_media(client, "feature", duration=3600.0)
    trailer = _make_media(client, "trailer", duration=120.0)
    s = client.post("/api/showings", json={
        "title": "In Use",
        "scheduled_start": "2026-07-03T19:00:00",
        "items": [
            {"media_id": trailer, "role": "trailer"},
            {"media_id": feature, "role": "feature"},
        ],
    })
    assert s.status_code == 201, s.text

    # Both the feature and a playlisted trailer are protected.
    assert client.delete(f"/api/media/{feature}").status_code == 409
    assert client.delete(f"/api/media/{trailer}").status_code == 409

    # Once the showing is gone, the media can be removed.
    client.delete(f"/api/showings/{s.json()['id']}")
    assert client.delete(f"/api/media/{feature}").status_code == 204
    assert client.delete(f"/api/media/{trailer}").status_code == 204


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


def test_playback_preview_proxy(client, monkeypatch):
    from app.services import playback_client
    from app.services.playback_client import PlaybackUnavailable

    monkeypatch.setattr(playback_client, "preview", lambda: (b"\xff\xd8JPG", "image/jpeg"))
    r = client.get("/api/playback/preview")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content == b"\xff\xd8JPG"

    monkeypatch.setattr(playback_client, "preview", lambda: None)
    assert client.get("/api/playback/preview").status_code == 404

    def _down():
        raise PlaybackUnavailable("down")

    monkeypatch.setattr(playback_client, "preview", _down)
    assert client.get("/api/playback/preview").status_code == 503


def test_seat_grid(client):
    grid = client.get("/api/tickets/seat-grid").json()
    assert grid["rows"] == ["A", "B", "C", "D", "E", "F"]
    assert grid["numbers"] == [1, 2, 3, 4, 5, 6]


def test_settings_defaults_and_update(client, monkeypatch):
    from app.services import playback_client

    configured = []
    monkeypatch.setattr(playback_client, "configure", lambda payload: configured.append(payload))

    s = client.get("/api/settings").json()
    assert s["video_output_ids"] == []
    assert s["audio_mode"] == "passthrough"
    assert s["idle_screen_mode"] == "black"
    assert s["idle_logo_path"] is None
    assert s["idle_logo_scale"] == "fit"

    r = client.put("/api/settings", json={
        "video_output_ids": ["decklink:0", "gpu:hdmi-0"],
        "audio_output_id": "sdi-embedded",
        "audio_mode": "pcm",
        "idle_screen_mode": "black",
        "idle_logo_scale": "fill",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["video_output_ids"] == ["decklink:0", "gpu:hdmi-0"]
    assert body["audio_output_id"] == "sdi-embedded"
    assert body["audio_mode"] == "pcm"
    assert body["idle_screen_mode"] == "black"
    assert body["idle_logo_scale"] == "fill"
    assert configured[-1]["idle_screen"] == {
        "mode": "black",
        "logo_path": None,
        "scale": "fill",
    }

    # rejects invalid audio mode
    assert client.put("/api/settings", json={"audio_mode": "bogus"}).status_code == 422
    assert client.put("/api/settings", json={"idle_screen_mode": "bogus"}).status_code == 422
    assert client.put("/api/settings", json={"idle_logo_scale": "bogus"}).status_code == 422


def test_time_format_setting(client, monkeypatch):
    from app.services import playback_client

    monkeypatch.setattr(playback_client, "configure", lambda payload: None)

    assert client.get("/api/settings").json()["time_format"] == "12h"  # default

    r = client.put("/api/settings", json={"time_format": "24h"})
    assert r.status_code == 200
    assert r.json()["time_format"] == "24h"
    assert client.get("/api/settings").json()["time_format"] == "24h"

    assert client.put("/api/settings", json={"time_format": "bogus"}).status_code == 422


def test_idle_logo_upload_requires_4k_image(client, tmp_path, monkeypatch):
    from app.routers import settings as settings_router
    from app.services import playback_client

    configured = []
    monkeypatch.setattr(settings_router, "_logo_dir", lambda: tmp_path)
    monkeypatch.setattr(playback_client, "configure", lambda payload: configured.append(payload))

    small = BytesIO()
    Image.new("RGB", (1920, 1080), "black").save(small, format="PNG")
    small.seek(0)
    r = client.post(
        "/api/settings/idle-logo",
        files={"file": ("small.png", small, "image/png")},
    )
    assert r.status_code == 422

    logo = BytesIO()
    Image.new("RGB", (3840, 2160), "black").save(logo, format="PNG")
    logo.seek(0)
    r = client.post(
        "/api/settings/idle-logo",
        files={"file": ("logo.png", logo, "image/png")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["width"] == 3840
    assert body["height"] == 2160
    assert body["idle_logo_path"] == str(tmp_path / "idle-logo.png")

    s = client.get("/api/settings").json()
    assert s["idle_screen_mode"] == "logo"
    assert s["idle_logo_path"] == str(tmp_path / "idle-logo.png")
    assert configured[-1]["idle_screen"]["mode"] == "logo"


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


def test_media_scan_finds_videos_in_nested_folders(client, tmp_path, monkeypatch):
    from app.database import SessionLocal
    from app.services import media_scan

    (tmp_path / "Movies" / "Feature").mkdir(parents=True)
    (tmp_path / "Trailers").mkdir()
    (tmp_path / "Movies" / "Feature" / "Nested Feature.MP4").write_bytes(b"video")
    (tmp_path / "Trailers" / "teaser.m2ts").write_bytes(b"video")
    (tmp_path / "not-video.txt").write_text("ignore me")

    monkeypatch.setattr(media_scan.settings, "media_root", str(tmp_path))
    monkeypatch.setattr(media_scan, "probe_metadata", lambda path: {
        "duration_seconds": 1.0, "width": 1920, "height": 1080, "fps": 24.0,
        "video_codec": "h264", "color_primaries": "", "transfer_characteristics": "",
        "is_hdr10": False, "aspect_ratio": "16:9", "file_size": 5, "bitrate": 0,
        "audio_codec": "", "audio_profile": "", "audio_channels": 0,
        "audio_channel_layout": "", "audio_format": "", "audio_summary": "",
    })

    db = SessionLocal()
    try:
        db.query(MediaFile).delete()
        db.commit()

        result = media_scan.scan_library(db)

        assert result == {"scanned": 2, "added": 2, "updated": 0}
        paths = {m.path for m in db.query(MediaFile).all()}
        assert paths == {
            str(tmp_path / "Movies" / "Feature" / "Nested Feature.MP4"),
            str(tmp_path / "Trailers" / "teaser.m2ts"),
        }
    finally:
        db.close()


def test_console_reserved_annotation(monkeypatch):
    """A connector reserved by the host console flags only the matching GPU
    output family; SDI and unrelated connectors are left selectable."""
    from app.routers import settings as s

    monkeypatch.setattr(s, "_reserved_connectors", lambda: ["HDMI-A-1"])
    out = s._annotate_reserved({
        "video": [
            {"id": "decklink:0", "name": "SDI", "type": "sdi"},
            {"id": "gpu:hdmi-0", "name": "HDMI", "type": "hdmi"},
            {"id": "gpu:dp-0", "name": "DP", "type": "displayport"},
        ],
        "audio": [],
    })
    by_id = {d["id"]: d for d in out["video"]}
    assert by_id["gpu:hdmi-0"]["reserved"] is True
    assert "HDMI-A-1" in by_id["gpu:hdmi-0"]["reserved_reason"]
    assert by_id["decklink:0"].get("reserved", False) is False
    assert by_id["gpu:dp-0"].get("reserved", False) is False

    # No reservation file -> nothing annotated.
    monkeypatch.setattr(s, "_reserved_connectors", lambda: [])
    clean = s._annotate_reserved({"video": [{"id": "gpu:hdmi-0", "name": "HDMI",
                                             "type": "hdmi"}], "audio": []})
    assert clean["video"][0].get("reserved", False) is False


def test_display_connector_annotation(monkeypatch):
    """Playback output choices carry discovered DRM display details so the UI
    can show the actual connector the operator is selecting."""
    from app.routers import settings as s

    monkeypatch.setattr(s, "_hardware_connectors", lambda: [
        {"name": "DP-1", "status": "connected", "card": "card1", "device": "/dev/dri/card1"},
        {"name": "HDMI-A-1", "status": "disconnected", "card": "card0"},
    ])

    out = s._annotate_display_connectors({
        "video": [
            {"id": "gpu:DP-1", "name": "GPU DP-1", "type": "displayport"},
            {"id": "gpu:HDMI-A-1", "name": "GPU HDMI", "type": "hdmi", "drm_device": "/dev/dri/card9"},
            {"id": "decklink:0", "name": "SDI", "type": "sdi"},
        ],
        "audio": [],
    })
    by_id = {d["id"]: d for d in out["video"]}
    assert by_id["gpu:DP-1"]["drm_connector"] == "DP-1"
    assert by_id["gpu:DP-1"]["drm_device"] == "/dev/dri/card1"
    assert by_id["gpu:DP-1"]["status"] == "connected"
    assert by_id["gpu:HDMI-A-1"]["drm_device"] == "/dev/dri/card9"
    assert by_id["gpu:HDMI-A-1"]["status"] == "disconnected"
    assert "drm_connector" not in by_id["decklink:0"]
