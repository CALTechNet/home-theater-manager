"""Application configuration, loaded from environment variables."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HTM_", env_file=".env", extra="ignore")

    # Storage
    database_url: str = "sqlite:////data/htm.db"

    # Where remote media is mounted (read-only) inside the backend container.
    media_root: str = "/mnt/media"

    # Playback control service (the host-side service; a mock in Phase 1).
    playback_url: str = "http://playback:9000"
    playback_timeout_s: float = 5.0

    # Tickets are generated as PDFs (receipt or full-page color) and printed from
    # the operator's workstation — no server-side printer driver. Default style.
    ticket_style: str = "receipt"       # receipt | fullpage

    # Theater identity printed on tickets.
    theater_name: str = "Home Cinema"

    # Hardware hints from deploy/discover.sh (informational; used by Phase 3).
    hardware_file: str = "/runtime/hardware.json"

    # Runtime-managed assets such as the idle display logo.
    runtime_dir: str = "/runtime"

    # Connectors reserved for the host's Linux console by deploy/console-routing.sh.
    # Used to warn when a playback video output collides with the text console.
    console_file: str = "/runtime/console.json"

    # Seat grid extents (rows A..max_row, seats 1..max_seat).
    seat_max_row: str = "F"
    seat_max_number: int = 6


@lru_cache
def get_settings() -> Settings:
    return Settings()
