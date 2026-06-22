"""Generate printable ticket PDFs.

The server only generates a PDF; the operator prints it from their workstation
to whatever printer they have (network, USB, thermal, or a normal 8.5x11 color
printer). Two styles are supported:

  * "receipt"  — 80mm thermal-receipt layout
  * "fullpage" — 8.5x11 portrait, color "movie ticket" design
"""
from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from ..config import get_settings
from ..models import Showing, Ticket

settings = get_settings()

INDIGO = colors.HexColor("#2b2d6e")
GOLD = colors.HexColor("#e5b94e")
INK = colors.HexColor("#1a1c23")


def _ticket_data(showing: Showing, ticket: Ticket) -> dict:
    start = showing.scheduled_start
    when = start.strftime("%a %b %d, %Y  %I:%M %p") if isinstance(start, datetime) else str(start)
    extras = [
        label for flag, label in (
            (ticket.incl_drink, "Drink"),
            (ticket.incl_popcorn, "Popcorn"),
            (ticket.incl_candy, "Candy"),
        ) if flag
    ]
    return {
        "theater": settings.theater_name,
        "title": showing.title or "(untitled)",
        "when": when,
        "runtime": f"{showing.computed_runtime_min} min" if showing.computed_runtime_min else "—",
        "seat": ticket.seat or "—",
        "name": ticket.name or "—",
        "extras": extras,
        "id": ticket.id,
        "copy": ticket.copy_index,
    }


# ---------------------------------------------------------------------------
# 80mm thermal receipt
# ---------------------------------------------------------------------------
def _receipt_pdf(d: dict) -> bytes:
    width = 80 * mm
    lines = [
        ("center", 13, True, d["theater"]),
        ("center", 10, False, "ADMIT ONE"),
        ("rule", 0, False, ""),
        ("left", 11, True, d["title"]),
        ("left", 9, False, f"When : {d['when']}"),
        ("left", 9, False, f"Run  : {d['runtime']}"),
        ("rule", 0, False, ""),
        ("left", 12, True, f"Seat : {d['seat']}"),
        ("left", 9, False, f"Name : {d['name']}"),
        ("left", 9, False, f"Extras: {', '.join(d['extras']) if d['extras'] else 'none'}"),
        ("rule", 0, False, ""),
        ("center", 8, False, f"Ticket #{d['id']} (copy {d['copy']})"),
        ("center", 10, True, "Enjoy the show!"),
    ]
    margin = 5 * mm
    line_h = 6 * mm
    height = margin * 2 + line_h * len(lines)

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    y = height - margin
    for align, size, bold, text in lines:
        if align == "rule":
            c.setStrokeColor(colors.grey)
            c.setDash(2, 2)
            c.line(margin, y - line_h / 2, width - margin, y - line_h / 2)
            c.setDash()
            y -= line_h
            continue
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        if align == "center":
            c.drawCentredString(width / 2, y - size, text)
        else:
            c.drawString(margin, y - size, text)
        y -= line_h
    c.showPage()
    c.save()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 8.5x11 color full-page ticket
# ---------------------------------------------------------------------------
def _chip(c, x, y, label, fill):
    w = 26 * mm
    h = 9 * mm
    c.setFillColor(fill)
    c.roundRect(x, y, w, h, 3 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(x + w / 2, y + 3 * mm, label)
    return x + w + 5 * mm


def _fullpage_pdf(d: dict) -> bytes:
    w, h = letter
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)

    # Outer ticket card.
    m = 18 * mm
    card_x, card_y = m, m
    card_w, card_h = w - 2 * m, h - 2 * m
    c.setFillColor(colors.HexColor("#f7f5ef"))
    c.roundRect(card_x, card_y, card_w, card_h, 8 * mm, stroke=0, fill=1)

    # Header band.
    band_h = 42 * mm
    c.setFillColor(INDIGO)
    c.roundRect(card_x, card_y + card_h - band_h, card_w, band_h, 8 * mm, stroke=0, fill=1)
    c.setFillColor(INDIGO)
    c.rect(card_x, card_y + card_h - band_h, card_w, band_h - 8 * mm, stroke=0, fill=1)

    c.setFillColor(GOLD)
    c.setFont("Helvetica-Bold", 26)
    c.drawCentredString(w / 2, card_y + card_h - 20 * mm, d["theater"])
    c.setFillColor(colors.white)
    c.setFont("Helvetica", 13)
    c.drawCentredString(w / 2, card_y + card_h - 30 * mm, "★  ADMIT ONE  ★")

    # Film title.
    cy = card_y + card_h - band_h - 22 * mm
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 30)
    c.drawCentredString(w / 2, cy, d["title"])

    # Showtime + runtime.
    cy -= 14 * mm
    c.setFont("Helvetica", 14)
    c.setFillColor(colors.HexColor("#444"))
    c.drawCentredString(w / 2, cy, d["when"])
    cy -= 9 * mm
    c.drawCentredString(w / 2, cy, f"Runtime: {d['runtime']}")

    # Perforation line.
    cy -= 16 * mm
    c.setStrokeColor(colors.HexColor("#bbb"))
    c.setDash(4, 4)
    c.line(card_x + 12 * mm, cy, card_x + card_w - 12 * mm, cy)
    c.setDash()

    # Stub: big seat + name.
    cy -= 6 * mm
    c.setFillColor(INK)
    c.setFont("Helvetica", 12)
    c.drawString(card_x + 16 * mm, cy - 10 * mm, "SEAT")
    c.setFont("Helvetica-Bold", 40)
    c.setFillColor(INDIGO)
    c.drawString(card_x + 16 * mm, cy - 26 * mm, d["seat"])

    c.setFillColor(INK)
    c.setFont("Helvetica", 12)
    c.drawString(card_x + 80 * mm, cy - 10 * mm, "GUEST")
    c.setFont("Helvetica-Bold", 20)
    c.drawString(card_x + 80 * mm, cy - 22 * mm, d["name"])

    # Extras chips.
    cy -= 40 * mm
    c.setFillColor(INK)
    c.setFont("Helvetica", 12)
    c.drawString(card_x + 16 * mm, cy, "INCLUDED")
    chip_y = cy - 14 * mm
    x = card_x + 16 * mm
    chip_colors = {"Drink": colors.HexColor("#4e8de5"),
                   "Popcorn": GOLD,
                   "Candy": colors.HexColor("#e5564e")}
    if d["extras"]:
        for label in d["extras"]:
            x = _chip(c, x, chip_y, label, chip_colors.get(label, INDIGO))
    else:
        c.setFont("Helvetica-Oblique", 12)
        c.setFillColor(colors.grey)
        c.drawString(x, chip_y + 2 * mm, "none")

    # Footer.
    c.setFillColor(colors.grey)
    c.setFont("Helvetica", 9)
    c.drawCentredString(w / 2, card_y + 12 * mm,
                        f"Ticket #{d['id']}  ·  copy {d['copy']}  ·  Enjoy the show!")
    c.showPage()
    c.save()
    return buf.getvalue()


def generate_pdf(showing: Showing, ticket: Ticket, style: str = "receipt") -> bytes:
    d = _ticket_data(showing, ticket)
    if style == "fullpage":
        return _fullpage_pdf(d)
    return _receipt_pdf(d)
