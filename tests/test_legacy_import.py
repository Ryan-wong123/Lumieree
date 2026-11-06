import os
import stat
from datetime import date

from lumieree.extensions import db
from lumieree.legacy_import import import_all, write_credentials
from lumieree.models import Appointment, Medicine, Patient, QueueItem, User, Visit


class FakeSource:
    def __init__(self, data, subs, emails=None):
        self.data, self.subs, self.emails = data, subs, emails or {}

    def documents(self, collection):
        return list(self.data.get(collection, {}).items())

    def subdocuments(self, collection, doc_id, sub):
        return list(self.subs.get((collection, doc_id, sub), {}).items())

    def auth_email(self, uid):
        return self.emails.get(uid)


def _source():
    data = {
        "users": {
            "uidA": {"email": "dr.tan@gmail.com", "role": "admin", "active": True, "created_at": "2024-01-02T03:04:05"},
            "uidB": {"role": "weird-role", "active": False},  # email only in Auth, bogus role
            "uidC": {"email": "dr.tan@gmail.com"},  # duplicate email / username
        },
        "patients": {
            "p1": {
                "owner_id": "uidA",
                "name": "Alice",
                "dob": "1980-05-06",
                "diabetes": "Yes",
                "hypertension": "No",
                "created_at": "2024-02-02T00:00:00",
                "last_visit": "2024-03-03T00:00:00",
            },
            "p2": {"owner_id": "ghost", "name": "Orphan"},  # unknown owner -> skipped
            "p3": {"owner_id": "uidA", "name": "  "},  # blank name -> skipped
        },
        "medicines": {
            "m1": {
                "owner_id": "uidA",
                "name": "Ginseng",
                "price": 5.5,
                "stock": 7,
                "expiry_date": "31/12/2030",
                "sku_id": "TCM-1",
                "barcode": 123,
            },
            "m2": {"owner_id": "uidA", "name": "Dup SKU", "price": "x", "stock": "bad", "sku_id": "TCM-1"},
        },
        "front_desk_queue": {
            "q1": {
                "owner_id": "uidA",
                "patient_id": "p1",
                "visit_id": "v1",
                "status": "completed",
                "timestamp": "2024-03-03T10:00:00",
                "items": [{"medicine_id": "m1", "name": "Ginseng", "quantity": 2}],
            },
            "q2": {"owner_id": "uidA", "prescription_id": "old"},  # legacy prescription-only row -> skipped
        },
        "appointments": {
            "a1": {"owner_id": "uidA", "date": "2030-01-01", "patient_name": "Alice", "slots": {"10": "x", 11: "y"}},
            "a2": {"owner_id": "uidA", "patient_name": "No date"},
        },
    }
    subs = {
        ("patients", "p1", "visits"): {
            "v1": {
                "date": "2024-03-03",
                "condition": "cough",
                "status": "confirmed",
                "services": [{"name": "Acu", "amount": 60}],
                "prescribed_meds": [{"name": "Ginseng"}],
            }
        }
    }
    return FakeSource(data, subs, emails={"uidB": "b@example.com"})


def test_import_maps_everything(app, tmp_path):
    report = import_all(_source())
    assert report.counts == {
        "users": 3,
        "patients": 1,
        "visits": 1,
        "medicines": 2,
        "front_desk_queue": 1,
        "appointments": 1,
    }
    assert report.skipped == {"patients": 2, "front_desk_queue": 1, "appointments": 1}

    users = {u.username: u for u in db.session.execute(db.select(User)).scalars()}
    assert set(users) == {"dr.tan", "b0", "dr.tan-2"}
    assert users["b0"].role == "staff" and users["b0"].active is False and users["b0"].email == "b@example.com"
    assert users["dr.tan-2"].email is None  # clashing e-mail dropped, account kept
    assert all(u.must_change_password for u in users.values())

    patient = db.session.execute(db.select(Patient)).scalar_one()
    assert patient.owner_id == users["dr.tan"].id and patient.dob == date(1980, 5, 6)
    assert patient.conditions == {"diabetes": "Yes", "hypertension": "No"}

    meds = {m.name: m for m in db.session.execute(db.select(Medicine)).scalars()}
    assert meds["Ginseng"].expiry_date == date(2030, 12, 31) and meds["Ginseng"].barcode == "123"
    assert meds["Dup SKU"].sku_id is None and meds["Dup SKU"].stock == 0

    queue = db.session.execute(db.select(QueueItem)).scalar_one()
    assert queue.items[0]["medicine_id"] == str(meds["Ginseng"].id)  # remapped to the new id
    assert queue.status == "completed" and queue.stock_deducted is True
    assert queue.visit_id == db.session.execute(db.select(Visit.id)).scalar_one()

    assert db.session.execute(db.select(Appointment)).scalar_one().slots == {"10": "x", "11": "y"}

    # temporary credentials: one per user, usable to log in, file readable only by the owner
    creds = {name: pw for name, _uid, pw in report.credentials}
    assert users["dr.tan"].check_password(creds["dr.tan"])
    out = tmp_path / "creds.csv"
    write_credentials(report, str(out))
    assert stat.S_IMODE(os.stat(out).st_mode) == 0o600


def test_dry_run_writes_nothing(app):
    import_all(_source(), commit=False)
    assert db.session.execute(db.select(User)).first() is None
