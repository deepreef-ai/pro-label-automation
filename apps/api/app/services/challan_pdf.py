"""Delivery challan PDF (``GET /api/dispatch/{id}/challan.pdf``): a simple synthetic A4 page."""
from __future__ import annotations

from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


def _qty(n: Any) -> str:
    return f"{int(n or 0):,}"


def render_challan(dc: dict[str, Any], company_name: str) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Delivery Challan {dc['id']}")
    width, height = A4
    left, right = 20 * mm, width - 20 * mm
    y = height - 25 * mm

    c.setFont("Helvetica-Bold", 16)
    c.drawString(left, y, company_name or "Label Plant")
    c.setFont("Helvetica-Bold", 13)
    c.drawRightString(right, y, "DELIVERY CHALLAN")
    y -= 8 * mm
    c.setFont("Helvetica", 10)
    c.drawString(left, y, f"Challan no: {dc['id']}")
    c.drawRightString(right, y, f"Date: {dc['date']}")
    y -= 4 * mm
    c.line(left, y, right, y)

    rows = [
        ("Client", f"{dc['client_name']} ({dc['client_id']})" if dc.get("client_id") else dc["client_name"]),
        ("Job card", dc["job_card"]),
        ("PO no", dc.get("po_no") or "-"),
        ("Product", dc.get("product") or "-"),
        ("Label size", dc.get("label_size") or "-"),
        ("Quantity (labels)", _qty(dc["qty"])),
        ("Boxes / rolls", _qty(dc["boxes"])),
        ("Vehicle no", dc.get("vehicle_no") or "-"),
        ("Transporter", dc.get("transporter") or "-"),
        ("LR no", dc.get("lr_no") or "-"),
        ("Freight (Rs)", f"{float(dc.get('freight') or 0):,.2f}"),
    ]
    y -= 10 * mm
    for label, value in rows:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(left, y, label)
        c.setFont("Helvetica", 10)
        c.drawString(left + 45 * mm, y, str(value)[:90])
        y -= 7 * mm

    y -= 15 * mm
    c.setFont("Helvetica", 9)
    c.drawString(left, y, "Received the above goods in good condition.")
    y -= 20 * mm
    c.drawString(left, y, "Receiver's signature")
    c.drawRightString(right, y, f"For {company_name or 'Label Plant'}")

    if dc.get("is_demo"):
        c.saveState()
        c.setFillColor(colors.Color(0.85, 0.1, 0.1, alpha=0.18))
        c.setFont("Helvetica-Bold", 90)
        c.translate(width / 2, height / 2)
        c.rotate(35)
        c.drawCentredString(0, 0, "DEMO")
        c.restoreState()
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(colors.red)
        c.drawString(left, 12 * mm, "DEMO: synthetic challan generated for the demo; not a real document.")

    c.showPage()
    c.save()
    return buf.getvalue()
