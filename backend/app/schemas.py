"""Pydantic request/response schemas."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


# ---- Media -----------------------------------------------------------------
class MediaFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    path: str
    kind: str
    title: str
    duration_seconds: float
    width: int
    height: int
    fps: float
    video_codec: str
    color_primaries: str
    transfer_characteristics: str
    is_hdr10: bool
    aspect_ratio: str
    file_size: int
    bitrate: int
    audio_codec: str
    audio_profile: str
    audio_channels: int
    audio_channel_layout: str
    audio_format: str
    audio_summary: str
    scanned_at: datetime


class MediaTagIn(BaseModel):
    kind: str | None = None   # trailer | feature
    title: str | None = None


class ScanResult(BaseModel):
    scanned: int
    added: int
    updated: int


class StorageOut(BaseModel):
    total: int          # bytes
    used: int           # bytes
    free: int           # bytes
    percent_used: float  # 0..100


# ---- Showings --------------------------------------------------------------
class ShowingItemIn(BaseModel):
    media_id: int
    role: str = "trailer"  # trailer | feature


class ShowingItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    media_id: int
    position: int
    role: str
    media: MediaFileOut


class ShowingCreate(BaseModel):
    title: str = ""
    scheduled_start: datetime
    feature_id: int | None = None
    # Ordered playlist (trailers first, feature usually last). If omitted,
    # the feature_id alone is used.
    items: list[ShowingItemIn] = []


class ShowingUpdate(BaseModel):
    title: str | None = None
    scheduled_start: datetime | None = None
    feature_id: int | None = None
    status: str | None = None
    items: list[ShowingItemIn] | None = None


class ShowingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    feature_id: int | None
    scheduled_start: datetime
    status: str
    computed_runtime_min: int
    created_at: datetime
    updated_at: datetime
    items: list[ShowingItemOut]


# ---- Tickets ---------------------------------------------------------------
class TicketCreate(BaseModel):
    showing_id: int
    seat: str | None = None
    name: str | None = None
    incl_drink: bool = False
    incl_popcorn: bool = False
    incl_candy: bool = False


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    showing_id: int
    seat: str | None
    name: str | None
    incl_drink: bool
    incl_popcorn: bool
    incl_candy: bool
    copy_index: int
    printed_at: datetime


# ---- Playback --------------------------------------------------------------
class PlaybackStateOut(BaseModel):
    state: str
    showing_id: int | None = None
    position_seconds: float = 0.0
    current_item: str | None = None


class SeatGridOut(BaseModel):
    rows: list[str]
    numbers: list[int]


# ---- Settings / outputs ----------------------------------------------------
class OutputDevice(BaseModel):
    id: str
    name: str
    type: str  # sdi | hdmi | displayport | analog | spdif ...
    drm_connector: str | None = None
    drm_device: str | None = None
    alsa_device: str | None = None
    status: str | None = None
    # True when deploy/console-routing.sh has reserved this connector for the
    # host's Linux text console. Advisory only — the UI warns but still allows
    # selection (output IDs are not yet 1:1 with DRM connector names; Phase 3).
    reserved: bool = False
    reserved_reason: str | None = None


class OutputsOut(BaseModel):
    video: list[OutputDevice]
    audio: list[OutputDevice]


class SettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    video_output_ids: list[str]
    audio_output_id: str | None
    audio_mode: str
    idle_screen_mode: str
    idle_logo_path: str | None
    idle_logo_scale: str
    time_format: str


class SettingsUpdate(BaseModel):
    video_output_ids: list[str] | None = None
    audio_output_id: str | None = None
    audio_mode: str | None = None
    idle_screen_mode: str | None = None
    idle_logo_scale: str | None = None
    time_format: str | None = None


class IdleLogoOut(BaseModel):
    idle_logo_path: str
    width: int
    height: int
