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

    # Thermal printer. When unset, tickets render to text and are NOT sent to
    # hardware (Phase 1 mock-friendly behavior).
    printer_kind: str = "none"          # none | usb | network | file
    printer_host: str = ""              # for network printers
    printer_port: int = 9100
    printer_usb_vendor: str = ""        # hex, e.g. "0x04b8"
    printer_usb_product: str = ""       # hex, e.g. "0x0e15"
    printer_file_path: str = "/data/tickets"  # for kind=file (debug)

    # Theater identity printed on tickets.
    theater_name: str = "Home Cinema"

    # Seat grid extents (rows A..max_row, seats 1..max_seat).
    seat_max_row: str = "F"
    seat_max_number: int = 6


@lru_cache
def get_settings() -> Settings:
    return Settings()
