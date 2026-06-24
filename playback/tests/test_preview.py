"""/preview endpoint: returns a JPEG of the current frame while playing."""
from fastapi.testclient import TestClient

from app import main
from app.player import SimulatedPlayer


def test_preview_returns_jpeg_when_playing(monkeypatch):
    monkeypatch.setattr(main, "player", SimulatedPlayer())
    grabbed = []
    monkeypatch.setattr(
        main,
        "_grab_frame",
        lambda path, position=0.0: grabbed.append(path) or b"\xff\xd8\xff\xe0JPEG",
    )
    client = TestClient(main.app)

    assert client.get("/preview").status_code == 404  # nothing loaded

    main.player.load(1, [{
        "path": "/mnt/media/movie.mkv",
        "display_path": "/home/htm/movie.mkv",
    }], None)
    main.player.start()
    r = client.get("/preview")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content == b"\xff\xd8\xff\xe0JPEG"
    assert grabbed[-1] == "/mnt/media/movie.mkv"


def test_preview_404_when_frame_grab_fails(monkeypatch):
    monkeypatch.setattr(main, "player", SimulatedPlayer())
    monkeypatch.setattr(main, "_grab_frame", lambda path, position=0.0: None)
    client = TestClient(main.app)

    main.player.load(1, [{"path": "/x.mkv"}], None)
    main.player.start()
    assert client.get("/preview").status_code == 404
