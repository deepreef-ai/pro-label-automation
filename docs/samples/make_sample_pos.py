"""Generate synthetic customer PO PDFs for the PO reader (``POST /api/jobs/from-po``).

Fictional clients from ``contract/fixtures`` only (commit-safe, no real names or data).
Run from the repo root:  python docs/samples/make_sample_pos.py
Needs reportlab (``pip install reportlab``).
"""
from __future__ import annotations

import random
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parent
SUPPLIER = "Demo Label Plant"
W, H = A4


def table_po(path: Path) -> None:
    """Classic tabular PO with a header block and an item table (Fresh Juice Co., CL-001)."""
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFillColor(colors.HexColor("#0b6e4f"))
    c.rect(0, H - 30 * mm, W, 30 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(20 * mm, H - 17 * mm, "Fresh Juice Co.")
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, H - 24 * mm, "Plot 14, MIDC Industrial Area, Pune 411019  |  GSTIN 27AAAFJ0000A1Z5 (sample)")
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, H - 42 * mm, "PURCHASE ORDER")
    c.setFont("Helvetica", 10)
    y = H - 52 * mm
    for line in ("PO No: FJC/PO/2026/0412", "PO Date: 18-11-2026", "Delivery date: 02-12-2026",
                 "Payment terms: 30 days"):
        c.drawString(20 * mm, y, line)
        y -= 6 * mm
    c.drawString(115 * mm, H - 52 * mm, f"To: {SUPPLIER}")
    c.drawString(115 * mm, H - 58 * mm, "Bhosari, Pune")
    c.drawString(115 * mm, H - 64 * mm, "Buyer: Fresh Juice Co.")

    y = H - 85 * mm
    cols = [(20, "Sr"), (30, "Description"), (105, "Size"), (130, "Material"), (160, "Qty"), (180, "Rate")]
    c.setFillColor(colors.HexColor("#e8f3ee"))
    c.rect(18 * mm, y - 2 * mm, 176 * mm, 8 * mm, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 9)
    for x, t in cols:
        c.drawString(x * mm, y, t)
    c.setFont("Helvetica", 9)
    y -= 9 * mm
    row = ["1", "Mango juice 200 ml bottle label", "60 x 80 mm", "PP White 250 mm", "50,000 nos", "Rs 0.60"]
    for (x, _), t in zip(cols, row, strict=True):
        c.drawString(x * mm, y, t)
    c.line(18 * mm, y - 4 * mm, 194 * mm, y - 4 * mm)
    y -= 12 * mm
    c.drawString(20 * mm, y, "Quantity: 50,000 labels   Rate: Rs 0.60 per label   Value before GST: Rs 30,000.00")
    y -= 6 * mm
    c.drawString(20 * mm, y, "Artwork as per last approved proof (repeat of JC-1316). Roll OD max 300 mm, core 76 mm.")
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(20 * mm, 30 * mm, "For Fresh Juice Co.  -  Authorised signatory (sample document, fictional company)")
    c.save()


def email_po(path: Path) -> None:
    """PO sent as an e-mail body printed to PDF (Lotus Cosmetics Pvt Ltd, CL-003)."""
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#555555"))
    y = H - 20 * mm
    for line in ("From: Neha Kulkarni <purchase@lotus.example>",
                 "To: orders@demolabel.example",
                 "Sent: Thursday, 19 November 2026 11:42",
                 "Subject: Purchase Order LCP-7781 - rose water labels"):
        c.drawString(20 * mm, y, line)
        y -= 5 * mm
    c.line(20 * mm, y, 190 * mm, y)
    c.setFillColor(colors.black)
    c.setFont("Times-Roman", 11)
    y -= 10 * mm
    body = [
        "Dear Sir,",
        "",
        "Please treat this mail as our Purchase Order No. LCP-7781 dated 19/11/2026.",
        "",
        "Customer: Lotus Cosmetics Pvt Ltd, Andheri East, Mumbai",
        "Item: Rose water 200 ml front label",
        "Size 60 x 90 mm on PET Clear 250 mm, 4 colour + gloss varnish",
        "Quantity: 60,000",
        "Rate @ Rs 0.85 per label (plus GST 18%)",
        "Deliver by 05-12-2026 to our Vasai warehouse.",
        "",
        "Kindly send the proof before printing. Same artwork as last order.",
        "",
        "Regards,",
        "Neha Kulkarni",
        "Purchase, Lotus Cosmetics Pvt Ltd (sample document, fictional company)",
    ]
    for line in body:
        c.drawString(20 * mm, y, line)
        y -= 6.5 * mm
    c.save()


def scanned_po(path: Path) -> None:
    """Typewriter-style PO with speckle and a stamp, like a scan (Kaveri Agro Foods, CL-007).

    The text layer is kept (the reader does not do OCR yet); only the look is scanned.
    """
    rnd = random.Random(7)
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFillColor(colors.HexColor("#f4f1e8"))
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#9a968c"))
    for _ in range(900):  # scanner speckle
        c.circle(rnd.uniform(0, W), rnd.uniform(0, H), rnd.uniform(0.15, 0.6), fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#222222"))
    c.setFont("Courier-Bold", 14)
    c.drawString(25 * mm, H - 30 * mm, "KAVERI AGRO FOODS")
    c.setFont("Courier", 10)
    lines = [
        "Hosur Road, Bengaluru 560068",
        "",
        "PURCHASE ORDER",
        "P.O. No. : KAF-PO-5530",
        "Date     : 16.11.2026",
        "",
        "M/s Demo Label Plant",
        "",
        "Please supply the following printed labels:",
        "",
        "Product  : Groundnut oil 1 L label",
        "Size     : 60 x 70 mm",
        "Stock    : PP Silver 250 mm",
        "Qty      : 80,000",
        "Rate     : Rs 0.65 each",
        "Required by : 30.11.2026",
        "",
        "Pack in rolls of 2000, outward wound.",
    ]
    y = H - 42 * mm
    for line in lines:
        c.drawString(25 * mm + rnd.uniform(-0.4, 0.4), y, line)
        y -= 6 * mm
    c.saveState()
    c.setStrokeColor(colors.HexColor("#3b5bb5"))
    c.setFillColor(colors.HexColor("#3b5bb5"))
    c.translate(140 * mm, 60 * mm)
    c.rotate(12)
    c.setLineWidth(1.5)
    c.circle(0, 0, 18 * mm, fill=0, stroke=1)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(0, 2 * mm, "KAVERI AGRO")
    c.drawCentredString(0, -3 * mm, "PURCHASE DEPT")
    c.restoreState()
    c.setFont("Courier", 8)
    c.drawString(25 * mm, 20 * mm, "(sample document, fictional company)")
    c.save()


def repeat_po(path: Path) -> None:
    """Short repeat-order note that only names the old job card (Orchid Wellness, CL-009)."""
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, H - 25 * mm, "Orchid Wellness")
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, H - 31 * mm, "Repeat order")
    y = H - 45 * mm
    for line in ("Purchase Order No: OW/RO/118", "Date: 2026-11-17",
                 "Buyer: Orchid Wellness", "",
                 "Repeat of your job JC-1315 (Ashwagandha capsules bottle label).",
                 "Quantity 75,000 labels. All other details as per previous order.",
                 "Required by 2026-12-08."):
        c.drawString(20 * mm, y, line)
        y -= 6.5 * mm
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(20 * mm, 20 * mm, "(sample document, fictional company)")
    c.save()


SAMPLES = {
    "po_fresh_juice_table.pdf": table_po,
    "po_lotus_email.pdf": email_po,
    "po_kaveri_scanned.pdf": scanned_po,
    "po_orchid_repeat.pdf": repeat_po,
}


if __name__ == "__main__":
    for name, fn in SAMPLES.items():
        fn(OUT / name)
        print("wrote", OUT / name)
