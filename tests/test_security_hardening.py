"""Audit log, two-factor authentication, CSP/SRI and patient data export/erasure."""

import re
import time
from datetime import date
from pathlib import Path

from lumieree import mfa
from lumieree.extensions import db
from lumieree.models import AuditLog, Patient, User, Visit
from tests.conftest import PASSWORD, Browser

ROOT = Path(__file__).resolve().parent.parent


def actions():
    return [a.action for a in db.session.execute(db.select(AuditLog).order_by(AuditLog.id)).scalars()]


def make_patient(owner, name="Test Patient"):
    patient = Patient(owner_id=owner.id, name=name, nric="S1234567D", contact="91234567")
    db.session.add(patient)
    db.session.flush()
    db.session.add(Visit(owner_id=owner.id, patient_id=patient.id, date=date.today(), condition="cough"))
    db.session.commit()
    return patient


def enable_mfa(browser):
    """Turn 2FA on through the UI. Returns (secret, recovery_codes)."""
    browser.post("/settings/mfa/start")
    html = browser.get("/settings").get_data(as_text=True)
    secret = re.search(r"<code>([A-Z2-7]{32})</code>", html).group(1)
    assert "data:image/svg+xml" in html  # QR code is rendered
    resp = browser.post("/settings/mfa/enable", {"code": mfa.code_at(secret)})
    assert resp.status_code == 200
    codes = re.findall(r"\b[0-9a-f]{5}-[0-9a-f]{5}\b", resp.get_data(as_text=True))
    assert len(codes) == mfa.BACKUP_CODE_COUNT
    return secret, codes


def next_code(secret):
    """A valid code for the next 30-second step (the current step was used while enabling)."""
    return mfa.code_at(secret, now=time.time() + mfa.STEP_SECONDS)


# ------------------------------------------------------------------ TOTP unit tests
def test_totp_matches_rfc6238_vector():
    # RFC 6238 appendix B, SHA-1, secret "12345678901234567890", T=59 -> 94287082 (6 digits: 287082)
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert mfa.code_at(secret, now=59) == "287082"


def test_totp_rejects_replay_bad_format_and_old_codes():
    secret = mfa.new_secret()
    now = 1_700_000_000
    code = mfa.code_at(secret, now=now)
    step = mfa.verify(secret, code, now=now)
    assert step == mfa.current_step(now)
    assert mfa.verify(secret, code, last_step=step, now=now) is None  # replay
    assert mfa.verify(secret, "12345", now=now) is None
    assert mfa.verify(secret, "abcdef", now=now) is None
    assert mfa.verify(secret, "", now=now) is None
    assert mfa.verify(secret, code, now=now + 5 * mfa.STEP_SECONDS) is None  # too old
    assert mfa.verify(secret, f"{code[:3]} {code[3:]}", now=now) == step  # spaces are tolerated


# ------------------------------------------------------------------------ audit log
def test_login_success_and_failure_are_audited(app, users, browser):
    browser.login("clinic-a", "wrong password entirely")
    browser.login("no-such-user-xyz", PASSWORD)
    browser.login("clinic-a")
    assert actions() == ["auth.login_failed", "auth.login_failed", "auth.login"]
    rows = db.session.execute(db.select(AuditLog).order_by(AuditLog.id)).scalars().all()
    assert rows[0].actor_username == "clinic-a" and rows[0].detail == "wrong password"
    # An unknown name is never stored (it may be a password typed into the wrong box).
    assert rows[1].actor_username is None and "no-such-user-xyz" not in (rows[1].detail or "")


def test_patient_access_is_audited(app, users, login_as):
    patient = make_patient(users["a"])
    browser = login_as("a")
    browser.get(f"/patients/{patient.id}/visits")
    entry = db.session.execute(db.select(AuditLog).where(AuditLog.action == "patient.view")).scalar_one()
    assert (entry.actor_id, entry.owner_id, entry.target_type, entry.target_id) == (
        users["a"].id,
        users["a"].id,
        "patient",
        patient.id,
    )


def test_audit_page_is_scoped_to_the_clinic_and_hidden_from_staff(app, users, login_as):
    a_browser = login_as("a")
    patient_a = make_patient(users["a"])
    a_browser.get(f"/patients/{patient_a.id}/visits")
    b_browser = login_as("b")

    a_html = a_browser.get("/admin/audit").get_data(as_text=True)
    b_html = b_browser.get("/admin/audit").get_data(as_text=True)
    assert "patient.view" in a_html and "clinic-a" in a_html
    assert "patient.view" not in b_html and "clinic-a" not in b_html  # tenant isolation
    assert "patient.view" in login_as("root").get("/admin/audit").get_data(as_text=True)  # super admin sees all
    assert login_as("staff").get("/admin/audit").status_code == 403


def test_audit_trail_survives_deleting_the_user(app, users, login_as):
    login_as("a")  # writes an auth.login row for clinic-a
    root = login_as("root")
    root.post(f"/admin/users/{users['a'].id}/delete")
    assert db.session.get(User, users["a"].id) is None
    rows = db.session.execute(db.select(AuditLog).where(AuditLog.action == "auth.login")).scalars().all()
    assert any(r.actor_username == "clinic-a" and r.actor_id is None for r in rows)
    assert "admin.user_delete" in actions()


# ------------------------------------------------------------------------------ MFA
def test_mfa_login_flow(app, users, login_as):
    browser = login_as("a")
    secret, _codes = enable_mfa(browser)
    assert db.session.get(User, users["a"].id).mfa_enabled
    browser.get("/logout")

    # Password alone is not enough.
    resp = browser.login("clinic-a")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/login/mfa")
    assert browser.get("/patients").status_code == 302  # still not signed in

    # Wrong code.
    resp = browser.post("/login/mfa", {"code": "000000"})
    assert resp.status_code == 200 and "Invalid code" in resp.get_data(as_text=True)
    assert browser.get("/patients").status_code == 302

    # Right code.
    good = next_code(secret)
    resp = browser.post("/login/mfa", {"code": good})
    assert resp.status_code == 302
    assert browser.get("/patients").status_code == 200

    # The same code cannot be used again (replay).
    browser.get("/logout")
    browser.login("clinic-a")
    resp = browser.post("/login/mfa", {"code": good})
    assert resp.status_code == 200 and browser.get("/patients").status_code == 302
    assert "auth.mfa_failed" in actions()


def test_mfa_recovery_code_works_once(app, users, login_as):
    browser = login_as("a")
    _secret, codes = enable_mfa(browser)
    browser.get("/logout")

    browser.login("clinic-a")
    assert browser.post("/login/mfa", {"code": codes[0]}).status_code == 302
    assert browser.get("/patients").status_code == 200
    assert len(db.session.get(User, users["a"].id).mfa_backup_codes) == mfa.BACKUP_CODE_COUNT - 1

    browser.get("/logout")
    browser.login("clinic-a")
    assert browser.post("/login/mfa", {"code": codes[0]}).status_code == 200  # already spent
    assert browser.post("/login/mfa", {"code": codes[1]}).status_code == 302  # another one is fine
    assert "auth.mfa_backup_used" in actions()


def test_mfa_locks_the_attempt_after_repeated_failures(app, users, login_as):
    browser = login_as("a")
    secret, _ = enable_mfa(browser)
    browser.get("/logout")
    browser.login("clinic-a")
    for _ in range(4):
        assert browser.post("/login/mfa", {"code": "111111"}).status_code == 200
    resp = browser.post("/login/mfa", {"code": "111111"})
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/login")
    # The half-finished login is gone: even a correct code now goes nowhere.
    resp = browser.post("/login/mfa", {"code": next_code(secret)})
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/login")
    assert browser.get("/patients").status_code == 302


def test_mfa_pending_login_expires(app, users, login_as, monkeypatch):
    browser = login_as("a")
    secret, _ = enable_mfa(browser)
    browser.get("/logout")
    browser.login("clinic-a")
    real_time = time.time
    monkeypatch.setattr("lumieree.auth.time.time", lambda: real_time() + 3600)
    resp = browser.post("/login/mfa", {"code": next_code(secret)})
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/login")
    assert browser.get("/patients").status_code == 302


def test_mfa_cannot_be_disabled_without_password_and_code(app, users, login_as):
    browser = login_as("a")
    secret, _ = enable_mfa(browser)
    user = db.session.get(User, users["a"].id)

    browser.post("/settings/mfa/disable", {"current_password": "wrong", "code": next_code(secret)})
    assert db.session.get(User, user.id).mfa_enabled
    browser.post("/settings/mfa/disable", {"current_password": PASSWORD, "code": "000000"})
    assert db.session.get(User, user.id).mfa_enabled

    browser.post("/settings/mfa/disable", {"current_password": PASSWORD, "code": next_code(secret)})
    db.session.expire_all()
    user = db.session.get(User, user.id)
    assert not user.mfa_enabled and user.totp_secret is None and user.mfa_backup_codes == []
    assert "auth.mfa_disabled" in actions()
    assert browser.get("/patients").status_code == 200  # this browser stays signed in


def test_super_admin_can_reset_a_users_mfa(app, users, login_as):
    enable_mfa(login_as("a"))
    root = login_as("root")
    html = root.get(f"/admin/users/{users['a'].id}/edit").get_data(as_text=True)
    assert 'name="reset_mfa"' in html
    root.post(
        f"/admin/users/{users['a'].id}/edit",
        {"role": "admin", "active": "on", "reset_mfa": "on"},
    )
    db.session.expire_all()
    assert not db.session.get(User, users["a"].id).mfa_enabled
    # The user can sign in with the password alone again.
    resp = Browser(app).login("clinic-a")
    assert resp.status_code == 302 and not resp.headers["Location"].endswith("/login/mfa")


def test_mfa_only_for_logged_in_users(app, users, browser):
    for path in ("/settings/mfa/start", "/settings/mfa/enable", "/settings/mfa/disable"):
        resp = browser.post(path)
        assert resp.status_code == 302 and "/login" in resp.headers["Location"]


# --------------------------------------------------------------------------- CSP / SRI
def test_csp_uses_a_fresh_nonce_and_no_unsafe_inline_scripts(app, users, login_as):
    browser = login_as("a")
    first = browser.get("/patients")
    second = browser.get("/patients")
    csp1, csp2 = first.headers["Content-Security-Policy"], second.headers["Content-Security-Policy"]
    script_src = next(d for d in csp1.split("; ") if d.startswith("script-src"))
    assert "'unsafe-inline'" not in script_src and "'unsafe-eval'" not in script_src
    nonce1 = re.search(r"'nonce-([^']+)'", csp1).group(1)
    nonce2 = re.search(r"'nonce-([^']+)'", csp2).group(1)
    assert nonce1 != nonce2
    html = first.get_data(as_text=True)
    inline = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", html)
    assert inline and all(f'nonce="{nonce1}"' in tag for tag in inline)


def test_templates_have_no_inline_handlers_and_cdn_assets_use_sri():
    for path in sorted((ROOT / "templates").glob("*.html")):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"<[^>]+\son[a-z]+\s*=", text), f"{path.name}: inline event handler (blocked by CSP)"
        for tag in re.findall(r"<(?:script|link)\b[^>]*>", text):
            if re.search(r"""(?:src|href)=["']https?://""", tag):
                assert "integrity=" in tag and 'crossorigin="anonymous"' in tag, f"{path.name}: no SRI on {tag}"
        for tag in re.findall(r"<script\b[^>]*>", text):
            if "src=" not in tag:
                assert "nonce=" in tag, f"{path.name}: inline script without nonce"


# --------------------------------------------------------- patient export and erasure
def test_patient_export_contains_record_and_visits_and_is_audited(app, users, login_as):
    patient = make_patient(users["a"], name="Alice Tan")
    browser = login_as("a")
    resp = browser.get(f"/patients/{patient.id}/export.json")
    assert resp.status_code == 200
    assert resp.mimetype == "application/json"
    assert f"patient-{patient.id}.json" in resp.headers["Content-Disposition"]
    data = resp.get_json()
    assert data["patient"]["name"] == "Alice Tan" and data["patient"]["nric"] == "S1234567D"
    assert len(data["visits"]) == 1 and data["visits"][0]["condition"] == "cough"
    assert "patient.export" in actions()


def test_patient_export_and_erasure_respect_tenant_isolation(app, users, login_as):
    patient = make_patient(users["a"], name="Alice Tan")
    other = login_as("b")

    resp = other.get(f"/patients/{patient.id}/export.json")
    assert resp.status_code == 302 and "Alice" not in resp.get_data(as_text=True)
    assert "patient.export" not in actions()

    other.post(f"/patients/delete/{patient.id}")
    assert db.session.get(Patient, patient.id) is not None
    assert "patient.delete" not in actions()


def test_patient_erasure_removes_the_record_and_is_audited(app, users, login_as):
    patient = make_patient(users["a"])
    pid = patient.id
    login_as("a").post(f"/patients/delete/{pid}")
    db.session.expire_all()
    assert db.session.get(Patient, pid) is None
    assert db.session.execute(db.select(Visit).where(Visit.patient_id == pid)).first() is None
    entry = db.session.execute(db.select(AuditLog).where(AuditLog.action == "patient.delete")).scalar_one()
    assert entry.target_id == pid
