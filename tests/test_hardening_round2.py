"""Mandatory two-factor for administrators, the break-glass reset, and erasure of appointment entries."""

from datetime import date

from lumieree.extensions import db
from lumieree.models import Appointment, AuditLog, Patient, User
from tests.test_security_hardening import enable_mfa


# ------------------------------------------------------- two-factor required for administrators
def test_admin_without_two_factor_is_confined_to_setup(app, users, login_as):
    app.config["REQUIRE_MFA_FOR_ADMINS"] = True
    admin = login_as("a")

    resp = admin.get("/patients")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/settings")
    settings = admin.get("/settings")
    assert settings.status_code == 200 and "Two-factor authentication is required" in settings.get_data(as_text=True)
    assert admin.get("/admin/dashboard").status_code == 302
    assert admin.get("/inventory").status_code == 302


def test_two_factor_setup_restores_access_and_cannot_be_turned_off(app, users, login_as):
    app.config["REQUIRE_MFA_FOR_ADMINS"] = True
    admin = login_as("a")
    secret, _codes = enable_mfa(admin)  # the setup pages are reachable while confined

    assert admin.get("/patients").status_code == 200
    assert admin.get("/admin/dashboard").status_code == 200
    import time

    from lumieree import mfa

    code = mfa.code_at(secret, now=time.time() + mfa.STEP_SECONDS)
    from tests.conftest import PASSWORD

    admin.post("/settings/mfa/disable", {"current_password": PASSWORD, "code": code})
    db.session.expire_all()
    assert db.session.get(User, users["a"].id).mfa_enabled  # refused: required for administrators
    page = admin.get("/settings").get_data(as_text=True)
    assert "cannot be turned off" in page and "mfa/disable" not in page


def test_requirement_applies_to_super_admins_but_not_staff(app, users, login_as):
    app.config["REQUIRE_MFA_FOR_ADMINS"] = True
    assert login_as("root").get("/admin/users").status_code == 302
    assert login_as("staff").get("/patients").status_code == 200  # staff may opt in, but are not forced


def test_requirement_can_be_switched_off(app, users, login_as):
    app.config["REQUIRE_MFA_FOR_ADMINS"] = False
    assert login_as("a").get("/patients").status_code == 200


def test_break_glass_cli_reset_clears_two_factor_and_is_audited(app, users, login_as):
    enable_mfa(login_as("a"))
    runner = app.test_cli_runner()

    result = runner.invoke(args=["reset-mfa", "--username", "Clinic-A"])
    assert result.exit_code == 0, result.output
    db.session.expire_all()
    user = db.session.get(User, users["a"].id)
    assert not user.mfa_enabled and user.totp_secret is None and user.mfa_backup_codes == []
    entry = db.session.execute(db.select(AuditLog).where(AuditLog.action == "admin.mfa_reset_cli")).scalar_one()
    assert entry.target_id == user.id and entry.ip is None

    missing = runner.invoke(args=["reset-mfa", "--username", "nobody"])
    assert missing.exit_code != 0 and "No such user" in missing.output


# ------------------------------------------------------- erasure also removes appointment entries
def _appointment(owner, name, contact):
    db.session.add(Appointment(owner_id=owner.id, date=date.today(), patient_name=name, contact=contact, slots={}))


def test_erasing_a_patient_removes_their_appointment_entries_only(app, users, login_as):
    patient = Patient(owner_id=users["a"].id, name="Alice Tan", contact="9123")
    db.session.add(patient)
    _appointment(users["a"], "Alice Tan", "9123")  # same name and number: removed
    _appointment(users["a"], "  alice tan ", None)  # same name, no number (case and spacing differ): removed
    _appointment(users["a"], "Alice Tan", "5555")  # same name, a different number: another person, kept
    _appointment(users["a"], "Bob Lim", "9123")  # different name: kept
    _appointment(users["b"], "Alice Tan", "9123")  # another clinic: never touched
    db.session.commit()
    pid = patient.id

    resp = login_as("a").post(f"/patients/delete/{pid}", follow_redirects=True)
    assert "2 appointment entries" in resp.get_data(as_text=True)

    db.session.expire_all()
    assert db.session.get(Patient, pid) is None
    left = db.session.execute(db.select(Appointment.owner_id, Appointment.patient_name, Appointment.contact)).all()
    assert sorted(left) == sorted(
        [
            (users["a"].id, "Alice Tan", "5555"),
            (users["a"].id, "Bob Lim", "9123"),
            (users["b"].id, "Alice Tan", "9123"),
        ]
    )
    entry = db.session.execute(db.select(AuditLog).where(AuditLog.action == "patient.delete")).scalar_one()
    assert "2 appointment entries" in entry.detail


def test_erasure_matches_by_name_when_the_patient_has_no_number(app, users, login_as):
    patient = Patient(owner_id=users["a"].id, name="Carol")
    db.session.add(patient)
    _appointment(users["a"], "Carol", "8000")
    _appointment(users["a"], "Carol", None)
    db.session.commit()
    login_as("a").post(f"/patients/delete/{patient.id}")
    assert db.session.execute(db.select(Appointment)).first() is None
