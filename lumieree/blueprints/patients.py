"""Patients and their visit records."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from itertools import zip_longest

from flask import Blueprint, Response, flash, json, redirect, render_template, request, url_for
from sqlalchemy import func, or_

from .. import audit
from ..auth import current_uid
from ..extensions import db
from ..models import CONDITION_FIELDS, Medicine, Patient, QueueItem, Visit
from ..translations import SERVICE_CATALOG
from ..utils import ValidationError, clean, parse_date, to_decimal, to_int, today

bp = Blueprint("patients", __name__)


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"


def _patient_from_form(form) -> dict:
    name = clean(form.get("name"), 255)
    if not name:
        raise ValidationError("Patient name is required.")
    dob_raw = clean(form.get("dob"), 40)
    dob = parse_date(dob_raw)
    if dob_raw and dob is None:
        raise ValidationError("Invalid date of birth.")
    western = clean(form.get("taking_western_medicine"), 8)
    conditions = {}
    for field in CONDITION_FIELDS:
        value = clean(form.get(field), 8)
        conditions[field] = value if value in ("Yes", "No") else ""
    return {
        "name": name,
        "nric": clean(form.get("nric"), 32) or None,
        "dob": dob,
        "gender": clean(form.get("gender"), 20) or None,
        "contact": clean(form.get("contact"), 64) or None,
        "email": clean(form.get("email"), 255) or None,
        "address": clean(form.get("address"), 500) or None,
        "conditions": conditions,
        "taking_western_medicine": western if western in ("Yes", "No") else None,
        "western_medicine_duration": clean(form.get("western_medicine_duration"), 255) or None,
        "other_conditions": clean(form.get("other_conditions"), 5000) or None,
        "drug_allergies": clean(form.get("drug_allergies"), 5000) or None,
    }


@bp.get("/patients")
def list_patients():
    q = clean(request.args.get("q"), 100)
    visit_counts = (
        db.select(Visit.patient_id, func.count(Visit.id).label("n"))
        .where(Visit.owner_id == current_uid())
        .group_by(Visit.patient_id)
        .subquery()
    )
    stmt = (
        db.select(Patient, func.coalesce(visit_counts.c.n, 0))
        .outerjoin(visit_counts, visit_counts.c.patient_id == Patient.id)
        .where(Patient.owner_id == current_uid())
        .order_by(Patient.name)
    )
    if q:
        pattern = _like(q)
        stmt = stmt.where(
            or_(
                Patient.name.ilike(pattern, escape="\\"),
                Patient.contact.ilike(pattern, escape="\\"),
                Patient.nric.ilike(pattern, escape="\\"),
            )
        )
    patients = []
    for patient, count in db.session.execute(stmt):
        data = patient.to_dict()
        data["visit_count"] = count
        patients.append(data)
    return render_template("patients.html", patients=patients)


@bp.route("/patients/add", methods=["GET", "POST"])
def add_patient():
    if request.method == "POST":
        try:
            data = _patient_from_form(request.form)
        except ValidationError as exc:
            flash(f"❌ {exc}")
            return render_template("add_patient.html"), 400
        patient = Patient(owner_id=current_uid(), **data)
        db.session.add(patient)
        db.session.commit()
        audit.record("patient.create", target_type="patient", target_id=patient.id)
        flash("Patient added!")
        return redirect(url_for("patients.list_patients"))
    return render_template("add_patient.html")


@bp.route("/patients/edit/<int:patient_id>", methods=["GET", "POST"])
def edit_patient(patient_id: int):
    patient = Patient.get_owned(current_uid(), patient_id)
    if patient is None:
        flash("❌ Patient not found.")
        return redirect(url_for("patients.list_patients"))

    if request.method == "POST":
        try:
            for key, value in _patient_from_form(request.form).items():
                setattr(patient, key, value)
        except ValidationError as exc:
            db.session.rollback()
            flash(f"❌ {exc}")
            return render_template("edit_patient.html", patient=patient.to_dict()), 400
        db.session.commit()
        audit.record("patient.update", target_type="patient", target_id=patient.id)
        flash("Patient updated successfully!")
        return redirect(url_for("patients.list_patients"))

    return render_template("edit_patient.html", patient=patient.to_dict())


@bp.post("/patients/delete/<int:patient_id>")
def delete_patient(patient_id: int):
    patient = Patient.get_owned(current_uid(), patient_id)
    if patient is None:
        flash("❌ Patient not found.")
    else:
        patient_id = patient.id
        db.session.delete(patient)  # visits cascade; queue rows keep history with patient_id NULL
        db.session.commit()
        audit.record("patient.delete", target_type="patient", target_id=patient_id, detail="erased with visits")
        flash("✅ Patient and their visit records deleted.")
    return redirect(url_for("patients.list_patients"))


@bp.get("/patients/<int:patient_id>/export.json")
def export_patient(patient_id: int):
    """Everything held about one patient (data-access request): their record and all visits, as JSON."""
    patient = Patient.get_owned(current_uid(), patient_id)
    if patient is None:
        flash("❌ Patient not found.")
        return redirect(url_for("patients.list_patients"))
    visits = db.session.execute(
        db.select(Visit)
        .where(Visit.owner_id == current_uid(), Visit.patient_id == patient.id)
        .order_by(Visit.date, Visit.id)
    ).scalars()
    payload = {
        "exported_at": datetime.now(UTC).isoformat(),
        "patient": patient.to_dict(),
        "visits": [v.to_dict() for v in visits],
    }
    audit.record("patient.export", target_type="patient", target_id=patient.id)
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename=patient-{patient.id}.json"},
    )


# ---------------------------------------------------------------------- visits
def _parse_meds(form, owned_medicine_ids: set[int]) -> list[dict]:
    meds = []
    rows = zip_longest(
        form.getlist("med_id"),
        form.getlist("med_name"),
        form.getlist("med_quantity"),
        form.getlist("med_dosage"),
        fillvalue="",
    )
    for med_id, name, qty, dosage in rows:
        name = clean(name, 255)
        if not name:
            continue
        med_id = clean(med_id, 20)
        meds.append(
            {
                "medicine_id": med_id if med_id.isdigit() and int(med_id) in owned_medicine_ids else "",
                "name": name,
                "quantity": to_int(qty, 1, minimum=1),
                "dosage": clean(dosage, 40),
            }
        )
    return meds


def _parse_services(form) -> list[dict]:
    services = []
    for name, amount in zip(form.getlist("service_name"), form.getlist("service_amount"), strict=False):
        name = clean(name, 255)
        if name:
            services.append({"name": name, "amount": float(to_decimal(amount, Decimal("0")))})
    return services


@bp.route("/patients/<int:patient_id>/visits", methods=["GET", "POST"])
def patient_visits(patient_id: int):
    owner = current_uid()
    patient = Patient.get_owned(owner, patient_id)
    if patient is None:
        flash("❌ Patient not found.")
        return redirect(url_for("patients.list_patients"))

    if request.method == "POST":
        action = request.form.get("action")
        owned_ids = set(db.session.execute(db.select(Medicine.id).where(Medicine.owner_id == owner)).scalars())
        meds = _parse_meds(request.form, owned_ids)
        services = _parse_services(request.form)
        status = "draft" if action == "save_draft" else "confirmed"

        # Only one draft per patient: replace any earlier one.
        db.session.execute(
            db.delete(Visit).where(Visit.owner_id == owner, Visit.patient_id == patient.id, Visit.status == "draft")
        )
        visit = Visit(
            owner_id=owner,
            patient_id=patient.id,
            date=parse_date(request.form.get("date")) or today(),
            condition=clean(request.form.get("condition"), 5000) or None,
            notes=clean(request.form.get("notes"), 5000) or None,
            discharge_advice=clean(request.form.get("discharge_advice"), 5000) or None,
            status=status,
            prescribed_meds=meds,
            services=services,
        )
        db.session.add(visit)
        db.session.flush()

        if status == "confirmed":
            patient.last_visit_at = datetime.now(UTC)
            if meds:
                db.session.add(QueueItem(owner_id=owner, patient_id=patient.id, visit_id=visit.id, items=meds))
        db.session.commit()
        audit.record("visit.create", target_type="patient", target_id=patient.id, detail=status)
        flash("Visit saved as draft." if status == "draft" else "Visit confirmed and sent to front desk.")
        return redirect(url_for("patients.patient_visits", patient_id=patient.id))

    audit.record("patient.view", target_type="patient", target_id=patient.id)
    visits = db.session.execute(
        db.select(Visit)
        .where(Visit.owner_id == owner, Visit.patient_id == patient.id, Visit.status == "confirmed")
        .order_by(Visit.date, Visit.id)
    ).scalars()
    draft = db.session.execute(
        db.select(Visit)
        .where(Visit.owner_id == owner, Visit.patient_id == patient.id, Visit.status == "draft")
        .order_by(Visit.id.desc())
        .limit(1)
    ).scalar_one_or_none()

    medicine_names, price_map = [], {}
    for m in db.session.execute(Medicine.owned_by(owner)).scalars():
        if m.name:
            medicine_names.append(m.name)
            price_map[m.name] = float(m.price or 0)

    return render_template(
        "patient_visits.html",
        patient=patient.to_dict(),
        visits=[v.to_dict() for v in visits],
        draft=draft.to_dict() if draft else None,
        medicine_names=medicine_names,
        medicine_price_map=price_map,
        service_catalog=SERVICE_CATALOG,
    )
