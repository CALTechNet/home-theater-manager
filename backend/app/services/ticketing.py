"""Render and (optionally) print thermal tickets via ESC/POS.

When printer_kind is 'none', tickets are rendered to text only (mock-friendly).
When 'file', the rendered receipt is written to a directory for inspection.
'usb'/'network' drive a real Epson printer via python-escpos.
"""
from datetime import datetime
from pathlib import Path

from ..config import get_settings
from ..models import Showing, Ticket

settings = get_settings()

_DIVIDER = "-" * 32


def render_text(showing: Showing, ticket: Ticket) -> str:
    """Human-readable receipt body (also used as the print source of truth)."""
    start = showing.scheduled_start
    start_str = start.strftime("%a %b %d, %Y  %I:%M %p") if isinstance(start, datetime) else str(start)
    runtime = f"{showing.computed_runtime_min} min" if showing.computed_runtime_min else "—"

    extras = [
        label for flag, label in (
            (ticket.incl_drink, "Drink"),
            (ticket.incl_popcorn, "Popcorn"),
            (ticket.incl_candy, "Candy"),
        ) if flag
    ]

    lines = [
        settings.theater_name.center(32),
        "ADMIT ONE".center(32),
        _DIVIDER,
        f"Film : {showing.title or '(untitled)'}",
        f"When : {start_str}",
        f"Run  : {runtime}",
        _DIVIDER,
        f"Seat : {ticket.seat or '—'}",
        f"Name : {ticket.name or '—'}",
        f"Extras: {', '.join(extras) if extras else 'none'}",
        _DIVIDER,
        f"Ticket #{ticket.id}  (copy {ticket.copy_index})",
        "Enjoy the show!".center(32),
    ]
    return "\n".join(lines)


def _build_escpos_printer():
    """Create a python-escpos printer for the configured backend, or None."""
    kind = settings.printer_kind
    if kind == "network":
        from escpos.printer import Network
        return Network(settings.printer_host, port=settings.printer_port)
    if kind == "usb":
        from escpos.printer import Usb
        return Usb(int(settings.printer_usb_vendor, 16), int(settings.printer_usb_product, 16))
    return None


def print_ticket(showing: Showing, ticket: Ticket) -> tuple[bool, str]:
    """Render and dispatch a ticket. Returns (printed_to_hardware, rendered_text)."""
    text = render_text(showing, ticket)
    kind = settings.printer_kind

    if kind == "file":
        out_dir = Path(settings.printer_file_path)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"ticket_{ticket.id}_copy{ticket.copy_index}.txt").write_text(text)
        return False, text

    if kind in ("usb", "network"):
        printer = _build_escpos_printer()
        if printer is not None:
            printer.set(align="center")
            printer.text(text + "\n")
            printer.cut()
            return True, text

    # kind == "none" (or misconfigured): render only.
    return False, text
