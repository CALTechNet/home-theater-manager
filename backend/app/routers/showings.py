"""Showing CRUD + the data behind the New Showing wizard and Schedule tab."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import MediaFile, Showing
from ..schemas import ShowingCreate, ShowingItemIn, ShowingOut, ShowingUpdate
from ..services import scheduler
from ..services.showings import compute_runtime_min, replace_items

router = APIRouter(prefix="/api/showings", tags=["showings"])


def _media_map(db: Session, item_specs: list[ShowingItemIn]) -> dict[int, MediaFile]:
    ids = {s.media_id for s in item_specs}
    rows = db.query(MediaFile).filter(MediaFile.id.in_(ids)).all() if ids else []
    return {m.id: m for m in rows}


def _default_items(create: ShowingCreate) -> list[ShowingItemIn]:
    """If no explicit playlist, build one from feature_id alone."""
    if create.items:
        return create.items
    if create.feature_id is not None:
        return [ShowingItemIn(media_id=create.feature_id, role="feature")]
    return []


@router.get("", response_model=list[ShowingOut])
def list_showings(
    start: datetime | None = Query(None, description="inclusive lower bound"),
    end: datetime | None = Query(None, description="exclusive upper bound"),
    db: Session = Depends(get_db),
):
    q = db.query(Showing)
    if start is not None:
        q = q.filter(Showing.scheduled_start >= start)
    if end is not None:
        q = q.filter(Showing.scheduled_start < end)
    return q.order_by(Showing.scheduled_start).all()


@router.get("/{showing_id}", response_model=ShowingOut)
def get_showing(showing_id: int, db: Session = Depends(get_db)):
    showing = db.get(Showing, showing_id)
    if showing is None:
        raise HTTPException(404, "showing not found")
    return showing


@router.post("", response_model=ShowingOut, status_code=201)
def create_showing(body: ShowingCreate, db: Session = Depends(get_db)):
    showing = Showing(
        title=body.title,
        scheduled_start=body.scheduled_start,
        feature_id=body.feature_id,
        status="scheduled",
    )
    item_specs = _default_items(body)
    media_by_id = _media_map(db, item_specs)
    replace_items(showing, [(s.media_id, s.role) for s in item_specs], media_by_id)
    showing.computed_runtime_min = compute_runtime_min(showing.items)

    db.add(showing)
    db.commit()
    db.refresh(showing)
    scheduler.schedule_showing(showing)
    return showing


@router.patch("/{showing_id}", response_model=ShowingOut)
def update_showing(showing_id: int, body: ShowingUpdate, db: Session = Depends(get_db)):
    showing = db.get(Showing, showing_id)
    if showing is None:
        raise HTTPException(404, "showing not found")

    if body.title is not None:
        showing.title = body.title
    if body.scheduled_start is not None:
        showing.scheduled_start = body.scheduled_start
    if body.feature_id is not None:
        showing.feature_id = body.feature_id
    if body.status is not None:
        showing.status = body.status
    if body.items is not None:
        media_by_id = _media_map(db, body.items)
        replace_items(showing, [(s.media_id, s.role) for s in body.items], media_by_id)

    showing.computed_runtime_min = compute_runtime_min(showing.items)
    db.commit()
    db.refresh(showing)

    # Reschedule (time/status may have changed).
    if showing.status == "scheduled":
        scheduler.schedule_showing(showing)
    else:
        scheduler.unschedule_showing(showing.id)
    return showing


@router.delete("/{showing_id}", status_code=204)
def delete_showing(showing_id: int, db: Session = Depends(get_db)):
    showing = db.get(Showing, showing_id)
    if showing is None:
        raise HTTPException(404, "showing not found")
    scheduler.unschedule_showing(showing.id)
    db.delete(showing)
    db.commit()
