"""SQLAlchemy models.

Multi-tenancy: every business row carries ``owner_id`` (the account that owns it).
All reads and writes in the blueprints must be scoped through :func:`owned` or the
``Model.owned_by`` helper so one account can never touch another account's data.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db

# JSONB on PostgreSQL, plain JSON elsewhere (SQLite is used by the unit tests).
JSONType = JSON().with_variant(JSONB(), "postgresql")

ROLES = ("staff", "admin", "super_admin")
CONDITION_FIELDS = (
    "diabetes",
    "hypertension",
    "heart_disease",
    "asthma",
    "stroke",
    "kidney_disease",
    "High Cholesterol",
)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _iso(value):
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(default=utcnow, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(default=utcnow, onupdate=utcnow, nullable=False)


class OwnedMixin:
    """Adds the tenant column and a scoped query helper."""

    @classmethod
    def owned_by(cls, owner_id: int):
        return db.select(cls).where(cls.owner_id == owner_id)

    @classmethod
    def get_owned(cls, owner_id: int, pk: int):
        """Return the row only if it belongs to ``owner_id``; otherwise ``None``."""
        if pk is None:
            return None
        return db.session.execute(db.select(cls).where(cls.id == pk, cls.owner_id == owner_id)).scalar_one_or_none()


class User(TimestampMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="staff", nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(default=False, nullable=False)
    # Bumped whenever credentials/role/active change so stale sessions are rejected.
    session_version: Mapped[int] = mapped_column(default=1, nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    last_login_at: Mapped[dt.datetime | None] = mapped_column()

    created_by: Mapped[User | None] = relationship(remote_side="User.id", lazy="joined")

    __table_args__ = (CheckConstraint("role in ('staff', 'admin', 'super_admin')", name="ck_users_role"),)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)
        self.session_version = (self.session_version or 0) + 1

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_super_admin(self) -> bool:
        return self.role == "super_admin"

    @property
    def is_admin(self) -> bool:
        return self.role in ("admin", "super_admin")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.username} ({self.role})>"


class Medicine(TimestampMixin, OwnedMixin, db.Model):
    __tablename__ = "medicines"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    sku_id: Mapped[str | None] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    english_name: Mapped[str | None] = mapped_column(String(255))
    company: Mapped[str | None] = mapped_column(String(255))
    type: Mapped[str | None] = mapped_column(String(60))
    barcode: Mapped[str | None] = mapped_column(String(64))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"), nullable=False)
    stock: Mapped[int] = mapped_column(default=0, nullable=False)
    expiry_date: Mapped[dt.date | None] = mapped_column()

    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_medicines_price_nonneg"),
        CheckConstraint("stock >= 0", name="ck_medicines_stock_nonneg"),
        UniqueConstraint("owner_id", "sku_id", name="uq_medicines_owner_sku"),
        Index("ix_medicines_owner_name", "owner_id", "name"),
        Index("ix_medicines_owner_barcode", "owner_id", "barcode"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sku_id": self.sku_id,
            "name": self.name,
            "english_name": self.english_name or "",
            "company": self.company or "",
            "type": self.type or "",
            "barcode": self.barcode or "",
            "price": float(self.price or 0),
            "stock": self.stock,
            "expiry_date": _iso(self.expiry_date) or "",
        }


class Patient(TimestampMixin, OwnedMixin, db.Model):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    nric: Mapped[str | None] = mapped_column(String(32))
    dob: Mapped[dt.date | None] = mapped_column()
    gender: Mapped[str | None] = mapped_column(String(20))
    contact: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(500))
    # {"diabetes": "Yes", "hypertension": "No", ...}
    conditions: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    taking_western_medicine: Mapped[str | None] = mapped_column(String(8))
    western_medicine_duration: Mapped[str | None] = mapped_column(String(255))
    other_conditions: Mapped[str | None] = mapped_column(Text)
    drug_allergies: Mapped[str | None] = mapped_column(Text)
    last_visit_at: Mapped[dt.datetime | None] = mapped_column()

    visits: Mapped[list[Visit]] = relationship(
        back_populates="patient", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        Index("ix_patients_owner_name", "owner_id", "name"),
        Index("ix_patients_owner_nric", "owner_id", "nric"),
    )

    def to_dict(self) -> dict:
        data = {
            "id": self.id,
            "name": self.name,
            "nric": self.nric or "",
            "dob": _iso(self.dob) or "",
            "gender": self.gender or "",
            "contact": self.contact or "",
            "email": self.email or "",
            "address": self.address or "",
            "taking_western_medicine": self.taking_western_medicine or "",
            "western_medicine_duration": self.western_medicine_duration or "",
            "other_conditions": self.other_conditions or "",
            "drug_allergies": self.drug_allergies or "",
        }
        for field in CONDITION_FIELDS:
            data[field] = (self.conditions or {}).get(field, "")
        return data


class Visit(OwnedMixin, db.Model):
    __tablename__ = "visits"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[dt.date] = mapped_column(nullable=False)
    condition: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    discharge_advice: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="confirmed", nullable=False)
    # Snapshots: [{"medicine_id": "12", "name": "...", "quantity": 3, "dosage": "grams"}]
    prescribed_meds: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    # [{"name": "Acupuncture", "amount": 60.0}]
    services: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(default=utcnow, nullable=False)

    patient: Mapped[Patient] = relationship(back_populates="visits")

    __table_args__ = (
        CheckConstraint("status in ('draft', 'confirmed')", name="ck_visits_status"),
        Index("ix_visits_owner_date", "owner_id", "date"),
        Index("ix_visits_patient", "patient_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "date": _iso(self.date),
            "condition": self.condition or "",
            "notes": self.notes or "",
            "discharge_advice": self.discharge_advice or "",
            "status": self.status,
            "prescribed_meds": self.prescribed_meds or [],
            "services": self.services or [],
            "created_at": _iso(self.created_at),
        }


class QueueItem(OwnedMixin, db.Model):
    """Front-desk prescription queue entry."""

    __tablename__ = "front_desk_queue"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id", ondelete="SET NULL"))
    visit_id: Mapped[int | None] = mapped_column(ForeignKey("visits.id", ondelete="SET NULL"))
    items: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="waiting", nullable=False)
    # True once stock has been deducted, so completing twice never deducts twice.
    stock_deducted: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(default=utcnow, nullable=False)

    patient: Mapped[Patient | None] = relationship()

    __table_args__ = (
        CheckConstraint("status in ('waiting', 'completed')", name="ck_queue_status"),
        Index("ix_queue_owner_status", "owner_id", "status", "created_at"),
    )


class Appointment(OwnedMixin, db.Model):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[dt.date] = mapped_column(nullable=False)
    patient_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact: Mapped[str | None] = mapped_column(String(64))
    # {"10": "text", "11": "text", ...}
    slots: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(default=utcnow, nullable=False)

    __table_args__ = (Index("ix_appointments_owner_date", "owner_id", "date"),)
