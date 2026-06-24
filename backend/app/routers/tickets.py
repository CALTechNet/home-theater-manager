"""Ticketing endpoints: seat grid, create, validate, list, and PDF generation.

The server generates a PDF (receipt or full-page color); the operator previews
or prints it from their workstation to whatever printer they have.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import Showing, Ticket
from ..schemas import SeatGridOut, TicketCreate, TicketOut, TicketValidate, TicketValidationOut
from ..services.ticketing import generate_pdf

router = APIRouter(prefix="/api/tickets", tags=["tickets"])
settings = get_settings()


@router.get("/seat-grid", response_model=SeatGridOut)
def seat_grid():
    rows = [chr(c) for c in range(ord("A"), ord(settings.seat_max_row) + 1)]
    numbers = list(range(1, settings.seat_max_number + 1))
    return SeatGridOut(rows=rows, numbers=numbers)


@router.get("", response_model=list[TicketOut])
def list_tickets(showing_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(Ticket)
    if showing_id is not None:
        q = q.filter(Ticket.showing_id == showing_id)
    return q.order_by(Ticket.printed_at.desc()).all()


@router.post("", response_model=TicketOut, status_code=201)
def create_ticket(body: TicketCreate, db: Session = Depends(get_db)):
    showing = db.get(Showing, body.showing_id)
    if showing is None:
        raise HTTPException(404, "showing not found")

    # copy_index increments per (showing, seat) so reprints are distinguishable.
    prior = (
        db.query(func.count(Ticket.id))
        .filter(Ticket.showing_id == body.showing_id, Ticket.seat == body.seat)
        .scalar()
    )
    ticket = Ticket(
        showing_id=body.showing_id,
        seat=body.seat,
        name=body.name,
        incl_drink=body.incl_drink,
        incl_popcorn=body.incl_popcorn,
        incl_candy=body.incl_candy,
        copy_index=(prior or 0) + 1,
        validation_code=Ticket.new_validation_code(),
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def _normalize_scan_code(raw: str) -> str:
    code = raw.strip()
    if code.startswith("HTM-TICKET:"):
        code = code.split(":", 1)[1]
    return code.strip()


@router.post("/validate", response_model=TicketValidationOut)
def validate_ticket(body: TicketValidate, db: Session = Depends(get_db)):
    code = _normalize_scan_code(body.code)
    if not code:
        return TicketValidationOut(status="invalid", message="No ticket code found")

    ticket = db.query(Ticket).filter(Ticket.validation_code == code).first()
    if ticket is None:
        return TicketValidationOut(status="invalid", message="Ticket was not found")

    showing = db.get(Showing, ticket.showing_id)
    if showing is None:
        return TicketValidationOut(status="invalid", message="Ticket showing was not found", ticket=ticket)

    if body.showing_id is not None and ticket.showing_id != body.showing_id:
        return TicketValidationOut(
            status="wrong_showing",
            message="Ticket belongs to a different showing",
            ticket=ticket,
            showing=showing,
        )

    if ticket.scanned_at is not None:
        return TicketValidationOut(
            status="already_scanned",
            message="Ticket has already been scanned",
            ticket=ticket,
            showing=showing,
        )

    ticket.scanned_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(ticket)
    return TicketValidationOut(status="valid", message="Ticket validated", ticket=ticket, showing=showing)


@router.get("/{ticket_id}/pdf")
def ticket_pdf(
    ticket_id: int,
    style: str = Query("receipt", pattern="^(receipt|fullpage)$"),
    db: Session = Depends(get_db),
):
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(404, "ticket not found")
    showing = db.get(Showing, ticket.showing_id)
    if showing is None:
        raise HTTPException(404, "showing not found")
    if not ticket.validation_code:
        ticket.validation_code = Ticket.new_validation_code()
        db.commit()
        db.refresh(ticket)
    pdf = generate_pdf(showing, ticket, style)
    filename = f"ticket_{ticket.id}_{style}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
