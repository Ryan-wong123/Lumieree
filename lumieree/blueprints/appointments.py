"""Appointment calendar: one row per patient per day, with hourly slots 10:00-20:00."""

from __future__ import annotations

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from ..auth import current_uid
from ..extensions import db
from ..models import Appointment
from ..utils import clean, parse_date, today

bp = Blueprint("appointments", __name__)

SLOT_HOURS = range(10, 21)
MAX_ROWS_PER_DAY = 200


def _event_color(count: int) -> str:
    return "#198754" if count <= 2 else "#ffc107" if count <= 5 else "#dc3545"


def _events() -> list[dict]:
    rows = db.session.execute(
        db.select(Appointment.date, db.func.count(Appointment.id))
        .where(Appointment.owner_id == current_uid())
        .group_by(Appointment.date)
    ).all()
    return [
        {
            "title": f"{count} bookings",
            "start": d.isoformat(),
            "allDay": True,
            "backgroundColor": _event_color(count),
            "borderColor": _event_color(count),
        }
        for d, count in rows
    ]


def _date_arg(name: str = "date"):
    return parse_date(request.values.get(name))


@bp.get("/appointments")
def view():
    selected = _date_arg() or today()
    rows = db.session.execute(
        Appointment.owned_by(current_uid()).where(Appointment.date == selected).order_by(Appointment.id)
    ).scalars()
    patients, slots = [], {}
    for a in rows:
        patients.append({"name": a.patient_name, "contact": a.contact or ""})
        slots[a.patient_name] = a.slots or {}
    return render_template(
        "appointments.html",
        patients=patients,
        appointments=slots,
        selected_date=selected.isoformat(),
        events=_events(),
    )


@bp.post("/appointments/save")
def save():
    day = _date_arg() or today()
    owner = current_uid()
    new_rows = []
    row = 1
    while f"patient_name_{row}" in request.form and row <= MAX_ROWS_PER_DAY:
        name = clean(request.form.get(f"patient_name_{row}"), 255)
        if name:
            new_rows.append(
                Appointment(
                    owner_id=owner,
                    date=day,
                    patient_name=name,
                    contact=clean(request.form.get(f"contact_{row}"), 64) or None,
                    slots={str(h): clean(request.form.get(f"slot_{row}_{h}"), 200) for h in SLOT_HOURS},
                )
            )
        row += 1

    # Replace the whole day in one transaction.
    db.session.execute(db.delete(Appointment).where(Appointment.owner_id == owner, Appointment.date == day))
    db.session.add_all(new_rows)
    db.session.commit()
    flash(f"Appointments saved for {day.isoformat()}")
    return redirect(url_for("appointments.view", date=day.isoformat()))


@bp.get("/appointments/json")
def day_json():
    day = _date_arg()
    if day is None:
        return jsonify(patients=[])
    rows = db.session.execute(
        Appointment.owned_by(current_uid()).where(Appointment.date == day).order_by(Appointment.id)
    ).scalars()
    return jsonify(
        patients=[{"name": a.patient_name, "contact": a.contact or "", "slots": a.slots or {}} for a in rows]
    )


@bp.post("/appointments/delete")
def delete():
    day = _date_arg()
    name = clean(request.form.get("patient_name"), 255)
    if day is None or not name:
        return "", 400
    db.session.execute(
        db.delete(Appointment).where(
            Appointment.owner_id == current_uid(), Appointment.date == day, Appointment.patient_name == name
        )
    )
    db.session.commit()
    return "", 204


@bp.get("/appointments/event_counts")
def event_counts():
    return jsonify(_events())
