"""One-off import of the legacy Firebase (Firestore + Authentication) data into PostgreSQL.

Run it with ``flask import-firestore`` (see docs/deployment.md). The transformation logic lives here and is
independent of ``firebase_admin`` so it can be unit-tested with a fake source.

What is migrated
    users            Firestore ``users`` docs (+ Firebase Auth e-mail)  ->  ``users``
    patients         ``patients`` + ``patients/*/visits``               ->  ``patients`` / ``visits``
    medicines        ``medicines``                                      ->  ``medicines``
    front_desk_queue ``front_desk_queue``                               ->  ``front_desk_queue``
    appointments     ``appointments``                                   ->  ``appointments``

Not migrated
    * Passwords: Firebase password hashes are not exported. Every user gets a random temporary password
      (written to the credentials file) and must choose a new one at first login.
    * ``prescriptions`` and queue rows that only reference a prescription: that legacy flow had no UI.
"""

from __future__ import annotations

import csv
import re
import secrets
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol

from .extensions import db
from .models import CONDITION_FIELDS, Appointment, Medicine, Patient, QueueItem, User, Visit
from .utils import parse_date, to_decimal, to_int


class Source(Protocol):
    """Minimal read interface over the legacy data store."""

    def documents(self, collection: str) -> Iterable[tuple[str, dict]]: ...

    def subdocuments(self, collection: str, doc_id: str, sub: str) -> Iterable[tuple[str, dict]]: ...

    def auth_email(self, uid: str) -> str | None: ...


@dataclass
class Report:
    counts: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    credentials: list[tuple[str, str, str]] = field(default_factory=list)  # (username, old uid, temp password)

    def bump(self, name: str, *, skipped: bool = False) -> None:
        bucket = self.skipped if skipped else self.counts
        bucket[name] = bucket.get(name, 0) + 1


def _dt(value) -> datetime:
    """Firestore timestamps may be datetimes or ISO strings (the legacy app stored ISO strings)."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return parse_date(value)


def _username_for(email: str | None, uid: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9._-]", "", (email or "").split("@")[0].lower()) or f"user-{uid[:8].lower()}"
    if not re.match(r"^[a-z0-9]", base):
        base = "u" + base
    base = base[:56].ljust(2, "0")
    candidate, n = base, 1
    while candidate in taken:
        n += 1
        candidate = f"{base}-{n}"
    taken.add(candidate)
    return candidate


def import_all(source: Source, *, commit: bool = True) -> Report:
    """Copy everything from ``source`` into the current database inside one transaction."""
    report = Report()
    taken: set[str] = set(db.session.execute(db.select(User.username)).scalars())
    user_map: dict[str, int] = {}
    patient_map: dict[str, int] = {}
    visit_map: dict[str, int] = {}

    # ---- users
    for uid, data in source.documents("users"):
        email = (data.get("email") or source.auth_email(uid) or "").strip().lower() or None
        username = _username_for(email, uid, taken)
        if email and db.session.execute(db.select(User.id).where(User.email == email)).first():
            email = None  # keep the account, drop the clashing address
        role = data.get("role") if data.get("role") in ("staff", "admin", "super_admin") else "staff"
        user = User(
            username=username,
            email=email,
            role=role,
            active=bool(data.get("active", True)),
            must_change_password=True,
            created_at=_dt(data.get("created_at")),
        )
        temp_password = secrets.token_urlsafe(15)
        user.set_password(temp_password)
        db.session.add(user)
        db.session.flush()
        user_map[uid] = user.id
        report.credentials.append((user.username, uid, temp_password))
        report.bump("users")

    def owner_of(data: dict) -> int | None:
        return user_map.get(data.get("owner_id"))

    # ---- patients and visits
    for pid, data in source.documents("patients"):
        owner = owner_of(data)
        if owner is None or not (data.get("name") or "").strip():
            report.bump("patients", skipped=True)
            continue
        patient = Patient(
            owner_id=owner,
            name=str(data["name"]).strip()[:255],
            nric=data.get("nric"),
            dob=_date(data.get("dob")),
            gender=data.get("gender"),
            contact=data.get("contact"),
            email=data.get("email"),
            address=data.get("address"),
            conditions={f: data.get(f) for f in CONDITION_FIELDS if data.get(f) in ("Yes", "No")},
            taking_western_medicine=data.get("taking_western_medicine"),
            western_medicine_duration=data.get("western_medicine_duration"),
            other_conditions=data.get("other_conditions"),
            drug_allergies=data.get("drug_allergies"),
            created_at=_dt(data.get("created_at")),
            updated_at=_dt(data.get("updated_at") or data.get("created_at")),
            last_visit_at=_dt(data["last_visit"]) if data.get("last_visit") else None,
        )
        db.session.add(patient)
        db.session.flush()
        patient_map[pid] = patient.id
        report.bump("patients")

        for vid, v in source.subdocuments("patients", pid, "visits"):
            visit = Visit(
                owner_id=owner,
                patient_id=patient.id,
                date=_date(v.get("date")) or _dt(v.get("created_at")).date(),
                condition=v.get("condition"),
                notes=v.get("notes"),
                discharge_advice=v.get("discharge_advice"),
                status="draft" if v.get("status") == "draft" else "confirmed",
                prescribed_meds=v.get("prescribed_meds") or [],
                services=v.get("services") or [],
                created_at=_dt(v.get("created_at")),
            )
            db.session.add(visit)
            db.session.flush()
            visit_map[vid] = visit.id
            report.bump("visits")

    # ---- medicines (remember old ids so queue items keep pointing at the right row)
    medicine_map: dict[str, int] = {}
    seen_skus: set[tuple[int, str]] = set()
    for mid, data in source.documents("medicines"):
        owner = owner_of(data)
        name = (data.get("name") or "").strip()
        if owner is None or not name:
            report.bump("medicines", skipped=True)
            continue
        sku = (data.get("sku_id") or "").strip() or None
        if sku and (owner, sku) in seen_skus:
            sku = None
        if sku:
            seen_skus.add((owner, sku))
        medicine = Medicine(
            owner_id=owner,
            sku_id=sku,
            name=name[:255],
            english_name=data.get("english_name"),
            company=data.get("company"),
            type=data.get("type"),
            barcode=str(data["barcode"]) if data.get("barcode") else None,
            price=to_decimal(data.get("price"), Decimal("0")),
            stock=to_int(data.get("stock"), 0),
            expiry_date=_date(data.get("expiry_date")),
        )
        db.session.add(medicine)
        db.session.flush()
        medicine_map[mid] = medicine.id
        report.bump("medicines")

    # ---- front desk queue
    for _qid, data in source.documents("front_desk_queue"):
        owner = owner_of(data)
        patient_id = patient_map.get(data.get("patient_id"))
        if owner is None or patient_id is None or "items" not in data:
            report.bump("front_desk_queue", skipped=True)
            continue
        items = []
        for entry in data.get("items") or []:
            entry = dict(entry)
            old = str(entry.get("medicine_id") or "")
            entry["medicine_id"] = str(medicine_map[old]) if old in medicine_map else ""
            items.append(entry)
        completed = data.get("status") == "completed"
        db.session.add(
            QueueItem(
                owner_id=owner,
                patient_id=patient_id,
                visit_id=visit_map.get(data.get("visit_id")),
                items=items,
                status="completed" if completed else "waiting",
                stock_deducted=completed,  # the legacy app already deducted stock on completion
                created_at=_dt(data.get("timestamp")),
            )
        )
        report.bump("front_desk_queue")

    # ---- appointments
    for _aid, data in source.documents("appointments"):
        owner, day = owner_of(data), _date(data.get("date"))
        if owner is None or day is None or not (data.get("patient_name") or "").strip():
            report.bump("appointments", skipped=True)
            continue
        db.session.add(
            Appointment(
                owner_id=owner,
                date=day,
                patient_name=str(data["patient_name"]).strip()[:255],
                contact=data.get("contact"),
                slots={str(k): str(v) for k, v in (data.get("slots") or {}).items()},
                created_at=_dt(data.get("timestamp")),
            )
        )
        report.bump("appointments")

    if commit:
        db.session.commit()
    else:
        db.session.rollback()
    return report


def write_credentials(report: Report, path: str) -> None:
    """Write temporary credentials with owner-only permissions."""
    import os

    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["username", "legacy_firebase_uid", "temporary_password"])
        writer.writerows(report.credentials)


class FirestoreSource:
    """Reads the legacy Firebase project. Requires ``pip install -r requirements-migrate.txt``."""

    def __init__(self, credentials_path: str):
        try:
            import firebase_admin
            from firebase_admin import auth, credentials, firestore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install firebase-admin first: pip install -r requirements-migrate.txt") from exc
        firebase_admin.initialize_app(credentials.Certificate(credentials_path))
        self._db = firestore.client()
        self._auth = auth

    def documents(self, collection):  # pragma: no cover - needs a live Firebase project
        for doc in self._db.collection(collection).stream():
            yield doc.id, doc.to_dict() or {}

    def subdocuments(self, collection, doc_id, sub):  # pragma: no cover
        for doc in self._db.collection(collection).document(doc_id).collection(sub).stream():
            yield doc.id, doc.to_dict() or {}

    def auth_email(self, uid):  # pragma: no cover
        try:
            return self._auth.get_user(uid).email
        except Exception:
            return None
