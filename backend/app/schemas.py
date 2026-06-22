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
    audio_summary: str
    scanned_at: datetime


class MediaTagIn(BaseModel):
    kind: str | None = None   # trailer | feature
    title: str | None = None


class ScanResult(BaseModel):
    scanned: int
    added: int
    updated: int


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


class TicketPrintResult(BaseModel):
    ticket: TicketOut
    printed: bool          # True if sent to hardware
    rendered_text: str     # human-readable preview of the receipt


# ---- Playback --------------------------------------------------------------
class PlaybackStateOut(BaseModel):
    state: str
    showing_id: int | None = None
    position_seconds: float = 0.0
    current_item: str | None = None


class SeatGridOut(BaseModel):
    rows: list[str]
    numbers: list[int]
