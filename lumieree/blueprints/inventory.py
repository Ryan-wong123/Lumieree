"""Medicine inventory: listing, CRUD, barcode stock adjustment, CSV import."""

from __future__ import annotations

import csv
import io
import re
import uuid
from decimal import Decimal

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy import case, func, or_

from ..auth import current_uid
from ..extensions import db
from ..models import Medicine
from ..utils import ValidationError, clean, parse_date, to_decimal, to_int

bp = Blueprint("inventory", __name__)

DEFAULT_TYPES = ("pills", "grams", "bottle")
MAX_IMPORT_ROWS = 5000


def _gen_sku() -> str:
    return "TCM-" + uuid.uuid4().hex[:8].upper()


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    return f"%{escaped}%"


def _medicine_from_form(form) -> dict:
    """Whitelisted, validated medicine fields (never trust arbitrary form keys)."""
    name = clean(form.get("name"), 255)
    if not name:
        raise ValidationError("Medicine name is required.")
    expiry_raw = clean(form.get("expiry_date"), 40)
    expiry = parse_date(expiry_raw)
    if expiry_raw and expiry is None:
        raise ValidationError("Invalid expiry date.")
    return {
        "name": name,
        "english_name": clean(form.get("english_name"), 255) or None,
        "company": clean(form.get("company"), 255) or None,
        "type": clean(form.get("type"), 60) or None,
        "barcode": clean(form.get("barcode"), 64) or None,
        "price": to_decimal(form.get("price")),
        "stock": to_int(form.get("stock")),
        "expiry_date": expiry,
    }


@bp.get("/api/medicines")
def medicine_names():
    rows = db.session.execute(Medicine.owned_by(current_uid())).scalars()
    results = [
        {
            "id": m.id,
            "name": m.name,
            "stock": m.stock,
            "price": float(m.price or 0),
            "available": m.stock > 0,
        }
        for m in rows
        if (m.name or "").strip()
    ]
    results.sort(key=lambda item: (not item["available"], item["name"].lower()))
    return jsonify(results=results)


@bp.get("/inventory")
def list_inventory():
    q = clean(request.args.get("q"), 100)
    stmt = Medicine.owned_by(current_uid())
    if q:
        pattern = _like(q)
        stmt = stmt.where(
            or_(
                Medicine.name.ilike(pattern, escape="\\"),
                Medicine.english_name.ilike(pattern, escape="\\"),
                Medicine.barcode.ilike(pattern, escape="\\"),
            )
        )
    stmt = stmt.order_by(Medicine.name, Medicine.expiry_date)
    medicines = [m.to_dict() for m in db.session.execute(stmt).scalars()]
    return render_template("inventory.html", medicines=medicines)


@bp.route("/inventory/add", methods=["GET", "POST"])
def add_medicine():
    if request.method == "POST":
        try:
            data = _medicine_from_form(request.form)
        except ValidationError as exc:
            flash(f"❌ {exc}")
            return render_template("add_medicine.html"), 400
        db.session.add(Medicine(owner_id=current_uid(), sku_id=_gen_sku(), **data))
        db.session.commit()
        flash("Medicine added successfully!")
        return redirect(url_for("inventory.list_inventory"))
    return render_template("add_medicine.html")


def _adjust_stock(medicine_id: int, delta: int) -> int | None:
    """Atomic stock change scoped to the tenant; stock never goes below zero."""
    expr = Medicine.stock + delta
    new_stock = case((expr < 0, 0), else_=expr)
    row = db.session.execute(
        db.update(Medicine)
        .where(Medicine.id == medicine_id, Medicine.owner_id == current_uid())
        .values(stock=new_stock)
        .returning(Medicine.stock)
    ).first()
    db.session.commit()
    return row[0] if row else None


@bp.post("/inventory/scan-combined")
def scan_combined():
    barcode = clean(request.form.get("manual_barcode"), 64)
    if not barcode:
        flash("❌ No barcode provided.")
        return redirect(url_for("inventory.list_inventory"))
    try:
        amount = to_int(request.form.get("adjust_amount", 1), minimum=1)
    except ValidationError:
        flash("❌ Invalid quantity.")
        return redirect(url_for("inventory.list_inventory"))
    decrease = request.form.get("adjust_type", "increase") == "decrease"

    med = db.session.execute(
        Medicine.owned_by(current_uid()).where(Medicine.barcode == barcode).limit(1)
    ).scalar_one_or_none()
    if med is None:
        flash(f"❌ Medicine with barcode {barcode} not found.")
        return redirect(url_for("inventory.list_inventory"))

    new_stock = _adjust_stock(med.id, -amount if decrease else amount)
    flash(f"✅ Stock {'decreased' if decrease else 'increased'} by {amount}. New stock: {new_stock}")
    return redirect(url_for("inventory.list_inventory"))


@bp.post("/inventory/adjust/<int:medicine_id>/increase")
def increase_stock(medicine_id: int):
    if _adjust_stock(medicine_id, 1) is None:
        flash("❌ Medicine not found.")
    else:
        flash("✅ Stock increased by 1.")
    return redirect(url_for("inventory.list_inventory"))


@bp.post("/inventory/adjust/<int:medicine_id>/set")
def set_stock(medicine_id: int):
    med = Medicine.get_owned(current_uid(), medicine_id)
    if med is None:
        flash("❌ Medicine not found.")
        return redirect(url_for("inventory.list_inventory"))
    try:
        med.stock = to_int(request.form.get("new_stock", 0))
    except ValidationError:
        flash("❌ Invalid stock value.")
        return redirect(url_for("inventory.list_inventory"))
    db.session.commit()
    flash("✅ Stock updated successfully.")
    return redirect(url_for("inventory.list_inventory"))


@bp.route("/inventory/edit/<int:medicine_id>", methods=["GET", "POST"])
def edit_medicine(medicine_id: int):
    med = Medicine.get_owned(current_uid(), medicine_id)
    if med is None:
        flash("❌ Medicine not found.")
        return redirect(url_for("inventory.list_inventory"))

    types = set(DEFAULT_TYPES)
    types.update(
        t
        for t in db.session.execute(
            db.select(Medicine.type).where(Medicine.owner_id == current_uid()).distinct()
        ).scalars()
        if t
    )

    if request.method == "POST":
        try:
            for key, value in _medicine_from_form(request.form).items():
                setattr(med, key, value)
        except ValidationError as exc:
            db.session.rollback()
            flash(f"❌ {exc}")
            return render_template("edit_medicine.html", medicine=med.to_dict(), medicine_types=sorted(types)), 400
        db.session.commit()
        flash("Medicine updated successfully!")
        return redirect(url_for("inventory.list_inventory"))

    return render_template("edit_medicine.html", medicine=med.to_dict(), medicine_types=sorted(types))


@bp.post("/inventory/delete/<int:medicine_id>")
def delete_medicine(medicine_id: int):
    med = Medicine.get_owned(current_uid(), medicine_id)
    if med is None:
        flash("❌ Medicine not found.")
    else:
        db.session.delete(med)
        db.session.commit()
        flash("Medicine deleted successfully.")
    return redirect(url_for("inventory.list_inventory"))


# ------------------------------------------------------------------ CSV import
def _canon(value) -> str:
    return re.sub(r"[\s/_-]+", "", clean(value, 100).lower())


def _get(row: dict, *keys: str):
    wanted = {_canon(k) for k in keys}
    for key, value in row.items():
        if _canon(key) in wanted:
            return value
    return None


@bp.post("/inventory/import_csv")
def import_csv():
    upload = request.files.get("csv_file")
    if not upload or not upload.filename:
        flash("❌ Please choose a CSV file.")
        return redirect(url_for("inventory.list_inventory"))
    if not upload.filename.lower().endswith(".csv"):
        flash("❌ File must be a .csv")
        return redirect(url_for("inventory.list_inventory"))

    try:
        text = upload.stream.read().decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
    except (UnicodeDecodeError, csv.Error):
        flash("❌ CSV could not be read. Save it as UTF-8 and try again.")
        return redirect(url_for("inventory.list_inventory"))

    if not rows:
        flash("❌ CSV is empty.")
        return redirect(url_for("inventory.list_inventory"))
    if len(rows) > MAX_IMPORT_ROWS:
        flash(f"❌ CSV has too many rows (max {MAX_IMPORT_ROWS}).")
        return redirect(url_for("inventory.list_inventory"))

    owner = current_uid()
    added = updated = skipped = 0

    for row in rows:
        name = clean(_get(row, "name", "medicine_name", "medicine name"), 255)
        if not name:
            skipped += 1
            continue
        sku_id = clean(_get(row, "sku_id", "sku id", "sku"), 40)
        english = clean(_get(row, "english_name", "english name", "medicine_english_name"), 255)
        company = clean(_get(row, "company"), 255)
        med_type = clean(_get(row, "type"), 60)
        expiry = parse_date(_get(row, "expiry_date", "expiry date"))
        price = to_decimal(_get(row, "price", "selling price"), Decimal("0"))
        quantity = to_int(_get(row, "quantity", "stock"), 0)

        match = None
        if sku_id:
            match = db.session.execute(
                Medicine.owned_by(owner).where(Medicine.sku_id == sku_id).limit(1)
            ).scalar_one_or_none()
        if match is None:
            match = db.session.execute(
                Medicine.owned_by(owner)
                .where(
                    Medicine.name == name,
                    func.coalesce(Medicine.company, "") == company,
                    func.coalesce(Medicine.type, "") == med_type,
                    Medicine.expiry_date.is_(expiry) if expiry is None else Medicine.expiry_date == expiry,
                )
                .limit(1)
            ).scalar_one_or_none()

        if match:
            match.name, match.company, match.type = name, company or None, med_type or None
            match.price, match.stock, match.expiry_date = price, quantity, expiry
            if english:
                match.english_name = english
            updated += 1
        else:
            db.session.add(
                Medicine(
                    owner_id=owner,
                    sku_id=sku_id or _gen_sku(),
                    name=name,
                    english_name=english or None,
                    company=company or None,
                    type=med_type or None,
                    price=price,
                    stock=quantity,
                    expiry_date=expiry,
                )
            )
            added += 1
        db.session.flush()

    db.session.commit()
    flash(f"✅ Import done. Added: {added}, Updated: {updated}, Skipped: {skipped}")
    return redirect(url_for("inventory.list_inventory"))
