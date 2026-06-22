"""Ticketing endpoints: seat grid, print, list, reprint."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import Showing, Ticket
from ..schemas import (
    SeatGridOut,
    TicketCreate,
    TicketOut,
    TicketPrintResult,
)
from ..services.ticketing import print_ticket

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


@router.post("", response_model=TicketPrintResult, status_code=201)
def create_and_print(body: TicketCreate, db: Session = Depends(get_db)):
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
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    printed, text = print_ticket(showing, ticket)
    return TicketPrintResult(ticket=ticket, printed=printed, rendered_text=text)


@router.post("/{ticket_id}/reprint", response_model=TicketPrintResult)
def reprint(ticket_id: int, db: Session = Depends(get_db)):
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(404, "ticket not found")
    showing = db.get(Showing, ticket.showing_id)
    if showing is None:
        raise HTTPException(404, "showing not found")
    printed, text = print_ticket(showing, ticket)
    return TicketPrintResult(ticket=ticket, printed=printed, rendered_text=text)
