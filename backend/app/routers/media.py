"""Media library endpoints: list, tag, scan."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import MediaFile
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
