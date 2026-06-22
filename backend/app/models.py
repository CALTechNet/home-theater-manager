"""SQLAlchemy ORM models. Mirrors the data model in ARCHITECTURE.md §5."""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MediaFile(Base):
    __tablename__ = "media_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String, unique=True, index=True)
    kind: Mapped[str] = mapped_column(String, default="feature")  # trailer | feature
    title: Mapped[str] = mapped_column(String, default="")

    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    fps: Mapped[float] = mapped_column(Float, default=0.0)

    video_codec: Mapped[str] = mapped_column(String, default="")
    color_primaries: Mapped[str] = mapped_column(String, default="")
    transfer_characteristics: Mapped[str] = mapped_column(String, default="")
    is_hdr10: Mapped[bool] = mapped_column(Boolean, default=False)
    audio_summary: Mapped[str] = mapped_column(String, default="")

    scanned_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Showing(Base):
    __tablename__ = "showings"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String, default="")
    feature_id: Mapped[int | None] = mapped_column(ForeignKey("media_files.id"), nullable=True)

    scheduled_start: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String, default="scheduled")
    # scheduled | playing | paused | done | canceled

    computed_runtime_min: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    feature: Mapped["MediaFile | None"] = relationship("MediaFile")
    items: Mapped[list["ShowingItem"]] = relationship(
        "ShowingItem",
        back_populates="showing",
        cascade="all, delete-orphan",
        order_by="ShowingItem.position",
    )
    tickets: Mapped[list["Ticket"]] = relationship(
        "Ticket", back_populates="showing", cascade="all, delete-orphan"
    )


class ShowingItem(Base):
    """An ordered entry in a showing's playlist (trailer or the feature)."""

    __tablename__ = "showing_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    showing_id: Mapped[int] = mapped_column(ForeignKey("showings.id"))
    media_id: Mapped[int] = mapped_column(ForeignKey("media_files.id"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    role: Mapped[str] = mapped_column(String, default="trailer")  # trailer | feature

    showing: Mapped["Showing"] = relationship("Showing", back_populates="items")
    media: Mapped["MediaFile"] = relationship("MediaFile")


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    showing_id: Mapped[int] = mapped_column(ForeignKey("showings.id"))
    seat: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    incl_drink: Mapped[bool] = mapped_column(Boolean, default=False)
    incl_popcorn: Mapped[bool] = mapped_column(Boolean, default=False)
    incl_candy: Mapped[bool] = mapped_column(Boolean, default=False)
    copy_index: Mapped[int] = mapped_column(Integer, default=1)
    printed_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    showing: Mapped["Showing"] = relationship("Showing", back_populates="tickets")
