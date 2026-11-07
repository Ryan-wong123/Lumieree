"""Clinic dashboard / CSV exports (admins) and account management (super admins)."""

from __future__ import annotations

import csv
import io

from flask import Blueprint, Response, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func

from ..auth import admin_required, create_user, current_uid, normalize_email, super_admin_required, validate_password
from ..extensions import db
from ..models import ROLES, Medicine, Patient, QueueItem, User, Visit
from ..utils import ValidationError, csv_safe, parse_date, today

bp = Blueprint("admin", __name__, url_prefix="/admin")

LOW_STOCK_THRESHOLD = 10


# ------------------------------------------------------------------- dashboard
@bp.get("/dashboard")
@admin_required
def dashboard():
    owner = current_uid()
    start = parse_date(request.args.get("start_date")) or today()
    end = parse_date(request.args.get("end_date")) or today()
    if start > end:
        start, end = end, start

    total_patients = db.session.scalar(db.select(func.count(Patient.id)).where(Patient.owner_id == owner))
    total_prescriptions = db.session.scalar(db.select(func.count(QueueItem.id)).where(QueueItem.owner_id == owner))

    visit_rows = db.session.execute(
        db.select(Visit, Patient.name)
        .join(Patient, Patient.id == Visit.patient_id)
        .where(Visit.owner_id == owner, Visit.status == "confirmed", Visit.date.between(start, end))
        .order_by(Visit.date.desc(), Visit.id.desc())
    ).all()
    visits = [{"patient": name, "condition": v.condition, "date": v.date.isoformat()} for v, name in visit_rows]

    low_stock = [
        m.to_dict()
        for m in db.session.execute(
            Medicine.owned_by(owner)
            .where(Medicine.stock <= LOW_STOCK_THRESHOLD)
            .order_by(Medicine.stock, Medicine.name)
        ).scalars()
    ]

    completed = db.session.execute(
        db.select(QueueItem)
        .where(QueueItem.owner_id == owner, QueueItem.status == "completed")
        .order_by(QueueItem.created_at.desc())
        .limit(5)
    ).scalars()
    recent = []
    for q in completed:
        patient = q.patient if q.patient and q.patient.owner_id == owner else None
        recent.append(
            {
                "patient_name": patient.name if patient else "Unknown",
                "status": q.status,
                "items": q.items or [],
                "timestamp": q.created_at.strftime("%Y-%m-%d %H:%M"),
            }
        )

    return render_template(
        "admin_dashboard.html",
        total_patients=total_patients,
        daily_visits=len(visits),
        total_prescriptions=total_prescriptions,
        low_stock=low_stock,
        today_visits=visits,
        recent_completed=recent,
        filter_start=start.isoformat(),
        filter_end=end.isoformat(),
    )


def _csv_response(header: list[str], rows: list[list], filename: str) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    for row in rows:
        writer.writerow([csv_safe(cell) for cell in row])
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@bp.get("/export/visits.csv")
@admin_required
def export_visits():
    rows = db.session.execute(
        db.select(Patient.name, Patient.nric, Visit.date, Visit.condition, Visit.notes, Visit.created_at)
        .join(Patient, Patient.id == Visit.patient_id)
        .where(Visit.owner_id == current_uid(), Visit.status == "confirmed")
        .order_by(Visit.date, Visit.id)
    ).all()
    return _csv_response(
        ["Patient Name", "NRIC", "Date", "Condition", "Notes", "Created At"],
        [[n, nric or "", d.isoformat(), c or "", notes or "", ca.isoformat()] for n, nric, d, c, notes, ca in rows],
        "visit_records.csv",
    )


@bp.get("/export/queue.csv")
@admin_required
def export_queue():
    owner = current_uid()
    queue = db.session.execute(
        db.select(QueueItem).where(QueueItem.owner_id == owner).order_by(QueueItem.created_at)
    ).scalars()
    rows = []
    for q in queue:
        patient = q.patient if q.patient and q.patient.owner_id == owner else None
        items = "; ".join(f"{i.get('quantity')}x {i.get('name')}" for i in (q.items or []))
        rows.append([patient.name if patient else "Unknown", q.status, q.created_at.isoformat(), items])
    return _csv_response(["Patient Name", "Status", "Timestamp", "Items"], rows, "queue_log.csv")


# ------------------------------------------------------------ user management
def _active_super_admin_count() -> int:
    return db.session.scalar(db.select(func.count(User.id)).where(User.role == "super_admin", User.active.is_(True)))


@bp.get("/users")
@super_admin_required
def users():
    all_users = db.session.execute(db.select(User).order_by(User.username)).scalars()
    return render_template("admin_users.html", users=all_users)


@bp.route("/users/create", methods=["GET", "POST"])
@super_admin_required
def users_create():
    if request.method == "POST":
        try:
            role = request.form.get("role", "staff")
            if role not in ("staff", "admin"):  # super admins are created via the CLI only
                raise ValidationError("Invalid role.")
            create_user(
                request.form.get("username", ""),
                request.form.get("password", ""),
                role=role,
                email=request.form.get("email"),
                created_by=g.user,
                must_change_password=True,
            )
        except ValidationError as exc:
            db.session.rollback()
            flash(f"❌ {exc}")
            return render_template("create_user.html"), 400
        flash("✅ User created. They must choose a new password at first login.")
        return redirect(url_for("admin.users"))
    return render_template("create_user.html")


@bp.route("/users/<int:uid>/edit", methods=["GET", "POST"])
@super_admin_required
def user_edit(uid: int):
    user = db.session.get(User, uid)
    if user is None:
        flash("❌ User not found.")
        return redirect(url_for("admin.users"))

    if request.method == "POST":
        try:
            new_role = request.form.get("role", user.role)
            if new_role not in ROLES:
                raise ValidationError("Invalid role.")
            active = request.form.get("active") == "on"
            new_email = normalize_email(request.form.get("new_email"))
            new_password = (request.form.get("new_password") or "").strip()

            if user.id == g.user.id and not active:
                raise ValidationError("You cannot disable your own account.")
            if user.id == g.user.id and new_role != user.role:
                raise ValidationError("You cannot change your own role.")
            losing_super = user.role == "super_admin" and user.active and (new_role != "super_admin" or not active)
            if losing_super and _active_super_admin_count() <= 1:
                raise ValidationError("You cannot remove or disable the last active super admin.")

            if new_email and new_email != user.email:
                clash = db.session.execute(
                    db.select(User).where(func.lower(User.email) == new_email, User.id != user.id)
                ).first()
                if clash:
                    raise ValidationError("That email is already in use.")
                user.email = new_email
            if new_password:
                if user.id == g.user.id:
                    raise ValidationError("Use Settings to change your own password.")
                validate_password(new_password, user.username)
                user.set_password(new_password)  # also invalidates their sessions
                user.must_change_password = True

            if new_role != user.role or active != user.active:
                user.session_version += 1  # force re-login so role/active changes apply now
            user.role, user.active = new_role, active
            db.session.commit()
            flash("✅ User updated.")
            return redirect(url_for("admin.users"))
        except ValidationError as exc:
            db.session.rollback()
            flash(f"❌ {exc}")

    return render_template("edit_user.html", u=user)


@bp.post("/users/<int:uid>/delete")
@super_admin_required
def user_delete(uid: int):
    user = db.session.get(User, uid)
    if user is None:
        flash("❌ User not found.")
    elif user.id == g.user.id:
        flash("❌ You cannot delete your own account.")
    elif user.role == "super_admin" and user.active and _active_super_admin_count() <= 1:
        flash("❌ You cannot delete the last active super admin.")
    else:
        # Patients, visits, medicines, queue and appointments cascade via foreign keys.
        db.session.delete(user)
        db.session.commit()
        flash("✅ User and all of their data were deleted.")
    return redirect(url_for("admin.users"))
