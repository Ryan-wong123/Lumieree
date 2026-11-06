"""Front-desk prescription queue: dispensing (stock deduction) and voiding."""

from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from sqlalchemy import case

from ..auth import current_uid
from ..extensions import db
from ..models import Medicine, QueueItem
from ..utils import to_int

bp = Blueprint("front_desk", __name__)


def _find_medicine(owner: int, entry: dict) -> Medicine | None:
    med_id = str(entry.get("medicine_id") or "").strip()
    if med_id.isdigit():
        med = Medicine.get_owned(owner, int(med_id))
        if med:
            return med
    name = (entry.get("name") or "").strip()
    if not name:
        return None
    return db.session.execute(
        Medicine.owned_by(owner).where(Medicine.name == name).order_by(Medicine.id).limit(1)
    ).scalar_one_or_none()


def _apply_stock(owner: int, items: list[dict], sign: int) -> None:
    """sign=-1 dispenses (deduct), sign=+1 restores. Stock is clamped at zero, atomically."""
    for entry in items:
        med = _find_medicine(owner, entry)
        if med is None:
            continue
        qty = to_int(entry.get("quantity"), 0, minimum=0)
        expr = Medicine.stock + sign * qty
        db.session.execute(
            db.update(Medicine)
            .where(Medicine.id == med.id, Medicine.owner_id == owner)
            .values(stock=case((expr < 0, 0), else_=expr))
        )


@bp.get("/front_desk")
def front_desk():
    owner = current_uid()
    rows = db.session.execute(
        db.select(QueueItem).where(QueueItem.owner_id == owner).order_by(QueueItem.created_at.desc())
    ).scalars()
    waiting, completed = [], []
    for entry in rows:
        patient = entry.patient if entry.patient and entry.patient.owner_id == owner else None
        item = {
            "id": entry.id,
            "status": entry.status,
            "patient_name": patient.name if patient else "Unknown (Deleted)",
            "items": entry.items or [],
        }
        (completed if entry.status == "completed" else waiting).append(item)
    return render_template("front_desk.html", waiting=waiting, completed=completed)


@bp.post("/front_desk/update/<int:queue_id>/<status>")
def update_status(queue_id: int, status: str):
    if status not in ("completed", "void"):
        abort(404)
    owner = current_uid()
    # Row lock so a double-click cannot deduct stock twice.
    entry = db.session.execute(
        db.select(QueueItem).where(QueueItem.id == queue_id, QueueItem.owner_id == owner).with_for_update()
    ).scalar_one_or_none()
    if entry is None:
        flash("❌ Queue item not found.")
        return redirect(url_for("front_desk.front_desk"))

    if status == "completed":
        if entry.status == "waiting":
            if not entry.stock_deducted:
                _apply_stock(owner, entry.items or [], -1)
                entry.stock_deducted = True
            entry.status = "completed"
            db.session.commit()
        return redirect(url_for("receipts.queue_receipt", queue_id=entry.id))

    # void: return a completed order to the waiting list and restore its stock
    if entry.status == "completed":
        if entry.stock_deducted:
            _apply_stock(owner, entry.items or [], +1)
            entry.stock_deducted = False
        entry.status = "waiting"
        db.session.commit()
    return redirect(url_for("front_desk.front_desk"))
