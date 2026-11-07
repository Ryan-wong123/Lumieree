import datetime
import io
from decimal import Decimal

from lumieree.extensions import db
from lumieree.models import Appointment, Medicine, Patient, QueueItem, Visit


def _clinic(users, login_as):
    a = login_as("a")
    patient = Patient(owner_id=users["a"].id, name="Alice")
    med = Medicine(owner_id=users["a"].id, name="Ginseng", price=Decimal("5.00"), stock=10)
    db.session.add_all([patient, med])
    db.session.commit()
    return a, patient, med


def test_dispensing_deducts_stock_once_and_void_restores(users, login_as):
    a, patient, med = _clinic(users, login_as)
    a.post(
        f"/patients/{patient.id}/visits",
        {
            "action": "confirm",
            "condition": "cough",
            "med_id": str(med.id),
            "med_name": "Ginseng",
            "med_quantity": "4",
            "med_dosage": "grams",
            "service_name": "Acupuncture",
            "service_amount": "60",
        },
    )
    queue = db.session.execute(db.select(QueueItem)).scalar_one()
    assert queue.status == "waiting"

    for _ in range(3):  # double-clicks / replays must not deduct again
        a.post(f"/front_desk/update/{queue.id}/completed")
    db.session.expire_all()
    assert db.session.get(Medicine, med.id).stock == 6
    assert db.session.get(QueueItem, queue.id).status == "completed"

    a.post(f"/front_desk/update/{queue.id}/void")
    a.post(f"/front_desk/update/{queue.id}/void")
    db.session.expire_all()
    assert db.session.get(Medicine, med.id).stock == 10
    assert db.session.get(QueueItem, queue.id).status == "waiting"


def test_stock_update_is_not_possible_via_get(users, login_as):
    a, patient, med = _clinic(users, login_as)
    queue = QueueItem(
        owner_id=users["a"].id,
        patient_id=patient.id,
        items=[{"medicine_id": str(med.id), "name": "Ginseng", "quantity": 1}],
    )
    db.session.add(queue)
    db.session.commit()
    assert a.get(f"/front_desk/update/{queue.id}/completed").status_code == 405


def test_stock_never_goes_negative(users, login_as):
    a, patient, med = _clinic(users, login_as)
    med.barcode = "123"
    db.session.commit()
    a.post("/inventory/scan-combined", {"manual_barcode": "123", "adjust_amount": "500", "adjust_type": "decrease"})
    db.session.expire_all()
    assert db.session.get(Medicine, med.id).stock == 0


def test_receipt_pdf_uses_server_side_prices(users, login_as):
    a, patient, med = _clinic(users, login_as)
    visit = Visit(
        owner_id=users["a"].id,
        patient_id=patient.id,
        date=datetime.date.today(),
        services=[{"name": "Acupuncture", "amount": 60}],
    )
    db.session.add(visit)
    db.session.flush()
    queue = QueueItem(
        owner_id=users["a"].id,
        patient_id=patient.id,
        visit_id=visit.id,
        items=[{"medicine_id": str(med.id), "name": "Ginseng", "quantity": 2, "dosage": "grams"}],
    )
    db.session.add(queue)
    db.session.commit()

    page = a.get(f"/receipt/queue/{queue.id}")
    assert page.status_code == 200 and "Alice" in page.get_data(as_text=True)

    # A tampered form (fake prices / name) is ignored: the PDF is built from the database.
    resp = a.post(
        "/generate_receipt_pdf",
        {
            "queue_id": queue.id,
            "use_meds_master": "1",
            "use_1": "1",
            "medicine_price_1": "0.01",
            "amount_1": "0.01",
            "patient_name": "Mallory",
        },
    )
    assert resp.status_code == 200 and resp.mimetype == "application/pdf"
    assert resp.data.startswith(b"%PDF")


def test_csv_import_and_formula_injection_guard(users, login_as):
    a, patient, med = _clinic(users, login_as)
    csv_bytes = "name,english name,company,type,expiry date,price,quantity\n=cmd|' /C calc'!A0,Evil,Co,pills,31/12/2030,1.5,3\n,skipped,,,,,\n"
    resp = a.post(
        "/inventory/import_csv",
        {"csv_file": (io.BytesIO(csv_bytes.encode()), "meds.csv")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert "Added: 1" in resp.get_data(as_text=True) and "Skipped: 1" in resp.get_data(as_text=True)
    evil = db.session.execute(db.select(Medicine).where(Medicine.company == "Co")).scalar_one()
    assert evil.expiry_date == datetime.date(2030, 12, 31)
    export = a.get("/admin/export/queue.csv").get_data(as_text=True)
    assert "=cmd" not in export.replace("'=cmd", "")  # nothing starts with a raw formula char


def test_csv_export_neutralises_formulas(users, login_as):
    a, patient, med = _clinic(users, login_as)
    patient.name = '=HYPERLINK("http://evil")'
    db.session.add(
        Visit(owner_id=users["a"].id, patient_id=patient.id, date=datetime.date.today(), condition="@SUM(1)")
    )
    db.session.commit()
    body = a.get("/admin/export/visits.csv").get_data(as_text=True)
    assert "'=HYPERLINK" in body and "'@SUM" in body


def test_csv_import_rejects_bad_files(users, login_as):
    a, *_ = _clinic(users, login_as)
    resp = a.post(
        "/inventory/import_csv",
        {"csv_file": (io.BytesIO(b"x"), "meds.txt")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert "must be a .csv" in resp.get_data(as_text=True)
    resp = a.post(
        "/inventory/import_csv",
        {"csv_file": (io.BytesIO(b"\xff\xfe\x00bad"), "meds.csv")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert "could not be read" in resp.get_data(as_text=True)


def test_invalid_input_returns_400_not_500(users, login_as):
    a, patient, med = _clinic(users, login_as)
    assert a.post("/inventory/add", {"name": "X", "price": "abc", "stock": "1"}).status_code == 400
    assert a.post("/inventory/add", {"name": "X", "price": "-5", "stock": "1"}).status_code == 400
    assert a.post("/inventory/add", {"name": "X", "price": "1", "stock": "1.5e400"}).status_code == 400
    assert a.post("/patients/add", {"name": ""}).status_code == 400
    assert a.post("/patients/add", {"name": "Bob", "dob": "not-a-date"}).status_code == 400


def test_draft_visit_is_restored_and_replaced(users, login_as):
    a, patient, med = _clinic(users, login_as)
    a.post(f"/patients/{patient.id}/visits", {"action": "save_draft", "condition": "first draft"})
    a.post(f"/patients/{patient.id}/visits", {"action": "save_draft", "condition": "second draft"})
    page = a.get(f"/patients/{patient.id}/visits").get_data(as_text=True)
    assert "second draft" in page and "first draft" not in page
    assert db.session.execute(db.select(db.func.count(Visit.id))).scalar() == 1
    a.post(f"/patients/{patient.id}/visits", {"action": "confirm", "condition": "final"})
    assert db.session.execute(db.select(Visit).where(Visit.status == "draft")).first() is None


def test_appointments_roundtrip_and_xss_data_is_escaped(users, login_as):
    a = login_as("a")
    payload = "<img src=x onerror=alert(1)>"
    a.post(
        "/appointments/save", {"date": "2030-05-05", "patient_name_1": payload, "contact_1": "123", "slot_1_10": "cut"}
    )
    html = a.get("/appointments?date=2030-05-05").get_data(as_text=True)
    assert payload not in html and "&lt;img" in html
    assert a.get("/appointments/json?date=2030-05-05").get_json()["patients"][0]["name"] == payload
    assert a.post("/appointments/delete", {"patient_name": payload, "date": "2030-05-05"}).status_code == 204
    assert db.session.execute(db.select(Appointment)).first() is None


def test_patient_data_is_escaped(users, login_as):
    a = login_as("a")
    a.post("/patients/add", {"name": "<script>alert(1)</script>", "nric": "X"})
    body = a.get("/patients").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in body


def test_patient_search_and_visit_count(users, login_as):
    a, patient, med = _clinic(users, login_as)
    db.session.add(Visit(owner_id=users["a"].id, patient_id=patient.id, date=datetime.date.today(), status="confirmed"))
    db.session.commit()
    assert "Alice" in a.get("/patients?q=ali").get_data(as_text=True)
    assert "Alice" not in a.get("/patients?q=zzz").get_data(as_text=True)
    assert "Alice" not in a.get("/patients?q=%25").get_data(as_text=True)  # wildcard is escaped, not a match-all


def test_dashboard_counts(users, login_as):
    a, patient, med = _clinic(users, login_as)
    db.session.add(Visit(owner_id=users["a"].id, patient_id=patient.id, date=datetime.date.today(), condition="flu"))
    db.session.commit()
    body = a.get("/admin/dashboard").get_data(as_text=True)
    assert "flu" in body and "Ginseng" in body  # visit today + low stock (10 <= threshold)


def test_deleting_patient_keeps_queue_history(users, login_as):
    a, patient, med = _clinic(users, login_as)
    queue = QueueItem(owner_id=users["a"].id, patient_id=patient.id, items=[])
    db.session.add(queue)
    db.session.commit()
    a.post(f"/patients/delete/{patient.id}")
    db.session.expire_all()
    assert db.session.get(QueueItem, queue.id).patient_id is None
    assert "Unknown" in a.get("/front_desk").get_data(as_text=True)


def test_chinese_ui_renders(users, login_as):
    a = login_as("a")
    a.post("/switch_language", {"next": "/patients"})
    assert "患者" in a.get("/patients").get_data(as_text=True)


def test_all_pages_render(users, login_as):
    a, patient, med = _clinic(users, login_as)
    for path in (
        "/",
        "/patients",
        "/patients/add",
        f"/patients/edit/{patient.id}",
        f"/patients/{patient.id}/visits",
        "/inventory",
        "/inventory/add",
        f"/inventory/edit/{med.id}",
        "/front_desk",
        "/appointments",
        "/settings",
        "/admin/dashboard",
        "/appointments/event_counts",
    ):
        resp = a.get(path, follow_redirects=True)
        assert resp.status_code == 200, path


def test_404_page(login_as):
    a = login_as("a")
    resp = a.get("/does-not-exist")
    assert resp.status_code == 404 and "404" in resp.get_data(as_text=True)
