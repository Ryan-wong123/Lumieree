import pytest

from lumieree.auth import create_user
from lumieree.extensions import db
from lumieree.models import User
from lumieree.utils import ValidationError

from .conftest import PASSWORD


def test_requires_login(browser):
    resp = browser.get("/patients")
    assert resp.status_code == 302 and "/login" in resp.headers["Location"]


def test_health_is_public(browser):
    assert browser.get("/healthz").status_code == 200
    assert browser.get("/readyz").status_code == 200


def test_login_success_and_wrong_password(browser, users):
    bad = browser.login("clinic-a", "wrong-password-123")
    assert bad.status_code == 200 and "Invalid credentials" in bad.get_data(as_text=True)
    unknown = browser.login("nobody", "wrong-password-123")
    assert "Invalid credentials" in unknown.get_data(as_text=True)
    ok = browser.login("clinic-a")
    assert ok.status_code == 302


def test_login_requires_csrf(browser, users):
    resp = browser.post("/login", {"username": "clinic-a", "password": PASSWORD}, token=False)
    assert resp.status_code == 400


def test_open_redirect_blocked(browser, users):
    token = browser.token()
    resp = browser.client.post(
        "/login?next=https://evil.example/", data={"username": "clinic-a", "password": PASSWORD, "csrf_token": token}
    )
    assert resp.status_code == 302 and "evil.example" not in resp.headers["Location"]


def test_safe_next_is_followed(browser, users):
    token = browser.token()
    resp = browser.client.post(
        "/login?next=/inventory", data={"username": "clinic-a", "password": PASSWORD, "csrf_token": token}
    )
    assert resp.headers["Location"].endswith("/inventory")


def test_language_switch_ignores_external_next(login_as):
    b = login_as("a")
    resp = b.post("/switch_language", {"next": "https://evil.example"})
    assert "evil.example" not in resp.headers["Location"]


def test_deactivation_takes_effect_immediately(app, users, login_as):
    b = login_as("staff")
    assert b.get("/patients").status_code == 200
    users["staff"].active = False
    db.session.commit()
    assert b.get("/patients").status_code == 302


def test_role_change_invalidates_session(app, users, login_as):
    b = login_as("root")
    assert b.get("/admin/users").status_code == 200
    users["root"].role = "staff"
    users["root"].session_version += 1
    db.session.commit()
    assert b.get("/admin/users").status_code == 302


def test_password_policy(app):
    with pytest.raises(ValidationError):
        create_user("shorty", "short")
    with pytest.raises(ValidationError):
        create_user("Bad Name!", PASSWORD)


def test_passwords_are_hashed(app, users):
    assert users["a"].password_hash != PASSWORD
    assert users["a"].password_hash.startswith(("scrypt:", "pbkdf2:"))


def test_settings_password_change_requires_current_password(login_as, users):
    b = login_as("a")
    resp = b.post("/settings", {"new_password": "a brand new password", "current_password": "nope"})
    assert "Current password is incorrect" in resp.get_data(as_text=True)
    resp = b.post("/settings", {"new_password": "a brand new password", "current_password": PASSWORD})
    assert "Account updated" in resp.get_data(as_text=True)
    assert db.session.get(User, users["a"].id).check_password("a brand new password")
    assert b.get("/patients").status_code == 200  # still logged in on this browser


def test_security_headers(browser):
    resp = browser.get("/login")
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]
    assert resp.headers["Cache-Control"] == "no-store"


def test_must_change_password_forces_settings(app, users, login_as):
    users["a"].must_change_password = True
    db.session.commit()
    b = login_as("a")
    resp = b.get("/patients")
    assert resp.status_code == 302 and "/settings" in resp.headers["Location"]


def test_login_is_rate_limited(app, users, browser):
    app.config["LOGIN_RATE_LIMIT"] = "3 per minute"
    statuses = [browser.login("clinic-a", "wrong-password-123").status_code for _ in range(5)]
    assert statuses[:3] == [200, 200, 200]
    assert 429 in statuses
