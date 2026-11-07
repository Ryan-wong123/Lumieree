"""Every resource must be invisible and immutable to other tenants (IDOR checks)."""

from decimal import Decimal

from lumieree.extensions import db
from lumieree.models import Appointment, Medicine, Patient, QueueItem, Visit


def _seed(owner):
    patient = Patient(owner_id=owner.id, name="Secret Patient", nric="S1234567A")
    med = Medicine(owner_id=owner.id, name="Ginseng", price=Decimal("5.00"), stock=10)
    db.session.add_all([patient, med])
    db.session.flush()
    visit = Visit(
        owner_id=owner.id,
        patient_id=patient.id,
        date=__import__("datetime").date.today(),
        condition="cough",
        prescribed_meds=[{"medicine_id": str(med.id), "name": "Ginseng", "quantity": 2, "dosage": "grams"}],
        services=[{"name": "Acupuncture", "amount": 60.0}],
    )
    db.session.add(visit)
    db.session.flush()
    queue = QueueItem(owner_id=owner.id, patient_id=patient.id, visit_id=visit.id, items=visit.prescribed_meds)
    db.session.add(queue)
    db.session.commit()
    return patient, med, visit, queue


def test_lists_only_show_own_data(users, login_as):
    _seed(users["b"])
    a = login_as("a")
    for path in ("/patients", "/inventory", "/front_desk", "/api/medicines"):
        body = a.get(path).get_data(as_text=True)
        assert "Secret Patient" not in body and "Ginseng" not in body, path


def test_cannot_read_or_modify_other_tenants_rows(users, login_as):
    patient, med, visit, queue = _seed(users["b"])
    a = login_as("a")

    assert "Secret Patient" not in a.get(f"/patients/edit/{patient.id}", follow_redirects=True).get_data(as_text=True)
    assert "Secret Patient" not in a.get(f"/patients/{patient.id}/visits", follow_redirects=True).get_data(as_text=True)
    assert "Ginseng" not in a.get(f"/inventory/edit/{med.id}", follow_redirects=True).get_data(as_text=True)
    a.post(f"/patients/edit/{patient.id}", {"name": "Hacked"})
    a.post(f"/patients/delete/{patient.id}")
    a.post(f"/inventory/delete/{med.id}")
    a.post(f"/inventory/adjust/{med.id}/increase")
    a.post(f"/inventory/adjust/{med.id}/set", {"new_stock": "999"})
    a.post(f"/front_desk/update/{queue.id}/completed")
    assert a.get(f"/receipt/queue/{queue.id}").status_code == 302
    assert a.post("/generate_receipt_pdf", {"queue_id": queue.id}).status_code == 404

    db.session.expire_all()
    assert db.session.get(Patient, patient.id).name == "Secret Patient"
    assert db.session.get(Medicine, med.id).stock == 10
    assert db.session.get(QueueItem, queue.id).status == "waiting"


def test_mass_assignment_cannot_change_owner(users, login_as):
    a = login_as("a")
    a.post("/patients/add", {"name": "Mine", "owner_id": str(users["b"].id)})
    patient = db.session.execute(db.select(Patient).where(Patient.name == "Mine")).scalar_one()
    assert patient.owner_id == users["a"].id
    a.post(f"/patients/edit/{patient.id}", {"name": "Mine", "owner_id": str(users["b"].id), "id": "1"})
    db.session.expire_all()
    assert db.session.get(Patient, patient.id).owner_id == users["a"].id


def test_exports_are_tenant_scoped(users, login_as):
    _seed(users["b"])
    a = login_as("a")
    assert "Secret Patient" not in a.get("/admin/export/visits.csv").get_data(as_text=True)
    assert "Ginseng" not in a.get("/admin/export/queue.csv").get_data(as_text=True)


def test_appointments_are_tenant_scoped(users, login_as):
    db.session.add(
        Appointment(
            owner_id=users["b"].id, date=__import__("datetime").date(2030, 1, 1), patient_name="Hidden", slots={}
        )
    )
    db.session.commit()
    a = login_as("a")
    assert "Hidden" not in a.get("/appointments?date=2030-01-01").get_data(as_text=True)
    assert a.get("/appointments/json?date=2030-01-01").get_json() == {"patients": []}
    a.post("/appointments/delete", {"patient_name": "Hidden", "date": "2030-01-01"})
    assert db.session.execute(db.select(Appointment)).first() is not None


def test_visit_cannot_reference_other_tenants_medicine(users, login_as):
    _, med, _, _ = _seed(users["b"])
    mine = Patient(owner_id=users["a"].id, name="Mine")
    db.session.add(mine)
    db.session.commit()
    a = login_as("a")
    a.post(
        f"/patients/{mine.id}/visits",
        {
            "action": "confirm",
            "condition": "x",
            "med_id": str(med.id),
            "med_name": "Ginseng",
            "med_quantity": "3",
            "med_dosage": "grams",
        },
    )
    queue = db.session.execute(db.select(QueueItem).where(QueueItem.owner_id == users["a"].id)).scalar_one()
    assert queue.items[0]["medicine_id"] == ""  # foreign id dropped
    a.post(f"/front_desk/update/{queue.id}/completed")
    db.session.expire_all()
    assert db.session.get(Medicine, med.id).stock == 10  # other tenant's stock untouched
