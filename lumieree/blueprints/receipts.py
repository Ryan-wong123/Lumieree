"""Receipt page and PDF generation.

Prices are always recomputed on the server from the database. The browser only says
which lines to include, so a tampered form cannot change what is printed.
"""

from __future__ import annotations

import io
import os
from datetime import datetime
from decimal import Decimal

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, url_for
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from ..auth import current_uid
from ..extensions import db
from ..models import QueueItem, Visit
from ..utils import clean, to_decimal, to_int
from .front_desk import _find_medicine

bp = Blueprint("receipts", __name__)

_FONTS: tuple[str, str] | None = None


def _cjk_fonts() -> tuple[str, str]:
    """Return (regular, bold) font names able to draw Chinese. Registered once per process."""
    global _FONTS
    if _FONTS:
        return _FONTS
    regular = bold = None
    font_dir = current_app.config.get("FONT_DIR") or os.path.join(current_app.root_path, "..", "static", "fonts")
    try:
        reg_path = os.path.join(font_dir, "NotoSansCJKsc-Regular.otf")
        bold_path = os.path.join(font_dir, "NotoSansCJKsc-Bold.otf")
        if os.path.exists(reg_path):
            pdfmetrics.registerFont(TTFont("NotoSansCJKsc-Regular", reg_path))
            regular = "NotoSansCJKsc-Regular"
        if os.path.exists(bold_path):
            pdfmetrics.registerFont(TTFont("NotoSansCJKsc-Bold", bold_path))
            bold = "NotoSansCJKsc-Bold"
    except Exception:  # CFF-flavoured .otf is not supported by TTFont; use the CID fallback.
        current_app.logger.warning("Could not load Noto CJK font; falling back to STSong-Light", exc_info=True)
        regular = bold = None
    if not regular:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        regular = "STSong-Light"
    _FONTS = (regular, bold or regular)
    return _FONTS


def _build_receipt(queue: QueueItem) -> dict:
    owner = current_uid()
    items, medicine_total = [], Decimal("0")
    for entry in queue.items or []:
        qty = to_int(entry.get("quantity"), 0, minimum=0)
        med = _find_medicine(owner, entry)
        price = Decimal(med.price) if med else Decimal("0")
        subtotal = price * qty
        medicine_total += subtotal
        items.append(
            {
                "name": med.name if med else entry.get("name", ""),
                "unit_price": float(price),
                "quantity": qty,
                "unit": (entry.get("dosage") or "").strip(),
                "subtotal": float(subtotal),
            }
        )
    services = []
    if queue.visit_id:
        visit = Visit.get_owned(owner, queue.visit_id)
        if visit:
            services = visit.services or []
    patient = queue.patient if queue.patient and queue.patient.owner_id == owner else None
    return {
        "patient": {"id": patient.id, "name": patient.name} if patient else None,
        "items": items,
        "total": round(float(medicine_total), 2),
        "services": services,
    }


def _load_queue(queue_id) -> QueueItem | None:
    if queue_id is None:
        return None
    return db.session.execute(
        db.select(QueueItem).where(QueueItem.id == queue_id, QueueItem.owner_id == current_uid())
    ).scalar_one_or_none()


@bp.get("/receipt/queue/<int:queue_id>")
def queue_receipt(queue_id: int):
    queue = _load_queue(queue_id)
    if queue is None:
        flash("❌ Queue item not found.")
        return redirect(url_for("front_desk.front_desk"))
    data = _build_receipt(queue)
    if data["patient"] is None:
        flash("❌ Patient not found.")
        return redirect(url_for("front_desk.front_desk"))
    return render_template(
        "receipts.html",
        patient=data["patient"],
        items=data["items"],
        total=data["total"],
        services=data["services"],
        queue_data={"id": queue.id, "visit_id": queue.visit_id},
    )


def _fit(pdf: canvas.Canvas, text: str, font: str, size: int, max_width: float) -> str:
    """Truncate with an ellipsis so long names never run over the amount column."""
    if pdf.stringWidth(text, font, size) <= max_width:
        return text
    while text and pdf.stringWidth(text + "…", font, size) > max_width:
        text = text[:-1]
    return text + "…"


@bp.post("/generate_receipt_pdf")
def generate_receipt_pdf():
    queue = _load_queue(to_int(request.form.get("queue_id"), -1, minimum=None))
    if queue is None:
        abort(404)
    data = _build_receipt(queue)
    if data["patient"] is None:
        abort(404)

    # Which lines did the user tick? (Only inclusion flags come from the browser.)
    include_meds = request.form.get("use_meds_master", "1") == "1" and bool(data["items"])
    medicine_total = Decimal(str(data["total"])) if include_meds else Decimal("0")
    services: list[tuple[str, Decimal]] = []
    for index, svc in enumerate(data["services"], start=1):
        if request.form.get(f"use_{index}"):
            services.append((clean(svc.get("name"), 255), to_decimal(svc.get("amount"), Decimal("0"))))
    grand_total = medicine_total + sum((amt for _, amt in services), Decimal("0"))

    # Manual single-line receipt when nothing was ticked.
    custom_desc = clean(request.form.get("custom_description"), 200)
    if not include_meds and not services and custom_desc and request.form.get("custom_grand_total"):
        custom_total = to_decimal(request.form.get("custom_grand_total"), Decimal("0"))
        services.append((custom_desc, custom_total))
        grand_total = custom_total

    cn_regular, cn_bold = _cjk_fonts()
    cfg = current_app.config
    now = datetime.now()
    bill_no = now.strftime("%Y%m%d%H%M%S")

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    pdf.setFont(cn_bold, 16)
    pdf.drawCentredString(width / 2, height - 40, cfg["CLINIC_NAME_ZH"])
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawCentredString(width / 2, height - 60, cfg["CLINIC_NAME"])
    pdf.setFont("Helvetica", 9)
    pdf.drawCentredString(width / 2, height - 75, f"Reg. No: {cfg['CLINIC_REG_NO']}")
    pdf.setFont("Helvetica", 10)
    pdf.drawCentredString(width / 2, height - 90, cfg["CLINIC_ADDRESS"])
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawCentredString(width / 2, height - 120, "Receipt")
    pdf.setFont("Helvetica", 12)
    pdf.drawRightString(width - 50, height - 140, f"No. {bill_no[-5:]}")

    y = height - 170
    pdf.setFont(cn_regular, 11)  # patient names may be Chinese
    pdf.drawString(50, y, _fit(pdf, f"To: {data['patient']['name']}", cn_regular, 11, width - 100))
    pdf.setFont("Helvetica", 11)
    pdf.drawString(50, y - 15, f"Visit Date: {now.strftime('%d-%m-%Y')}")
    pdf.drawString(50, y - 30, f"Bill No.: {bill_no}")

    y -= 70
    row_height = 20
    left, right = 50, width - 50
    rows = (1 if medicine_total > 0 else 0) + len(services) + 2
    top, bottom = y, y - rows * row_height
    pdf.rect(left, bottom, right - left, rows * row_height)

    pdf.setFont("Helvetica-Bold", 11)
    pdf.line(left, top - row_height, right, top - row_height)
    pdf.drawString(left + 10, top - 15, "Services Rendered")
    pdf.drawRightString(right - 10, top - 15, "Amount (S$)")

    cursor = top - row_height
    pdf.setFont("Helvetica", 10)
    if medicine_total > 0:
        cursor -= row_height
        pdf.line(left, cursor, right, cursor)
        pdf.drawString(left + 10, cursor + 5, "Medicines")
        pdf.drawRightString(right - 10, cursor + 5, f"{medicine_total:.2f}")
    for name, amount in services:
        cursor -= row_height
        pdf.line(left, cursor, right, cursor)
        pdf.setFont(cn_regular, 10)
        pdf.drawString(left + 10, cursor + 5, _fit(pdf, name, cn_regular, 10, right - left - 120))
        pdf.setFont("Helvetica", 10)
        pdf.drawRightString(right - 10, cursor + 5, f"{amount:.2f}")

    cursor -= row_height
    pdf.line(left, cursor, right, cursor)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(left + 10, cursor + 5, "Total")
    pdf.drawRightString(right - 10, cursor + 5, f"{grand_total:.2f}")

    pdf.line(60, 60, 160, 60)
    pdf.drawString(80, 45, "Date")
    pdf.line(width - 200, 60, width - 100, 60)
    pdf.drawString(width - 180, 45, "Physician's Signature")

    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"Receipt_{bill_no}.pdf", mimetype="application/pdf")
