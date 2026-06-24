"""Thin HTTP client to the playback control service.

Implements the control API in ARCHITECTURE.md §6. The management plane never
touches hardware directly; it only talks to this service.
"""
import httpx

from ..config import get_settings

settings = get_settings()


class PlaybackUnavailable(RuntimeError):
    """Raised when the playback service cannot be reached."""


def _client() -> httpx.Client:
    return httpx.Client(base_url=settings.playback_url, timeout=settings.playback_timeout_s)


def _post(path: str, json: dict | None = None) -> dict:
    try:
        with _client() as c:
            r = c.post(path, json=json or {})
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        raise PlaybackUnavailable(str(e)) from e


def _get(path: str) -> dict:
    try:
        with _client() as c:
            r = c.get(path)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        raise PlaybackUnavailable(str(e)) from e


def load(showing_id: int, items: list[dict], outputs: dict | None = None) -> dict:
    payload = {"showing_id": showing_id, "items": items}
    if outputs:
        payload["outputs"] = outputs
    return _post("/playback/load", payload)


def configure(outputs: dict) -> dict:
    """Apply output and idle-screen routing even when no showing is loaded."""
    return _post("/playback/configure", {"outputs": outputs})


def outputs() -> dict:
    """Available video/audio output devices reported by the playback service."""
    return _get("/outputs")


def reload_outputs() -> dict:
    """Ask playback to rebuild its output catalog after hardware discovery."""
    return _post("/outputs/reload")


def start() -> dict:
    return _post("/playback/start")


def pause() -> dict:
    return _post("/playback/pause")


def resume() -> dict:
    return _post("/playback/resume")


def stop() -> dict:
    return _post("/playback/stop")


def state() -> dict:
    return _get("/playback/state")


def preview() -> tuple[bytes, str] | None:
    """Fetch a JPEG snapshot of the current output. None when none is available (404)."""
    try:
        with _client() as c:
            r = c.get("/preview")
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content, r.headers.get("content-type", "image/jpeg")
    except httpx.HTTPError as e:
        raise PlaybackUnavailable(str(e)) from e
