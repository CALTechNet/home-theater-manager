"""Media library endpoints: list, tag, scan, delete."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import MediaFile, Showing, ShowingItem
from ..schemas import MediaFileOut, MediaTagIn, ScanResult
from ..services.media_scan import scan_library

router = APIRouter(prefix="/api/media", tags=["media"])


@router.get("", response_model=list[MediaFileOut])
def list_media(kind: str | None = None, db: Session = Depends(get_db)):
    q = db.query(MediaFile)
    if kind in ("trailer", "feature"):
        q = q.filter(MediaFile.kind == kind)
    return q.order_by(MediaFile.title).all()


@router.post("/scan", response_model=ScanResult)
def scan(db: Session = Depends(get_db)):
    return scan_library(db)


@router.patch("/{media_id}", response_model=MediaFileOut)
def tag_media(media_id: int, body: MediaTagIn, db: Session = Depends(get_db)):
    media = db.get(MediaFile, media_id)
    if media is None:
        raise HTTPException(404, "media not found")
    if body.kind is not None:
        if body.kind not in ("trailer", "feature"):
            raise HTTPException(422, "kind must be 'trailer' or 'feature'")
        media.kind = body.kind
    if body.title is not None:
        media.title = body.title
    db.commit()
    db.refresh(media)
    return media


@router.delete("/{media_id}", status_code=204)
def delete_media(media_id: int, db: Session = Depends(get_db)):
    """Remove a media record from the database.

    Refuses (409) if the media is still part of a showing's playlist so we never
    orphan ``showing_items``. Only the DB row is removed — the file on the
    read-only media mount is untouched and will be re-added on the next scan.
    """
    media = db.get(MediaFile, media_id)
    if media is None:
        raise HTTPException(404, "media not found")

    in_playlist = (
        db.query(ShowingItem).filter(ShowingItem.media_id == media_id).count()
    )
    as_feature = (
        db.query(Showing).filter(Showing.feature_id == media_id).count()
    )
    if in_playlist or as_feature:
        raise HTTPException(
            409,
            "media is used by one or more showings; remove it from those "
            "showings before deleting",
        )

    db.delete(media)
    db.commit()
