"""Thin HTTP client to the host-side playback control service (mock in Phase 1).

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


def outputs() -> dict:
    """Available video/audio output devices reported by the playback service."""
    return _get("/outputs")


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
