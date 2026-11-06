import re

import pytest
from flask import g

from lumieree import create_app
from lumieree.auth import create_user
from lumieree.config import TestingConfig
from lumieree.extensions import db

PASSWORD = "correct horse battery"


@pytest.fixture()
def app():
    app = create_app(TestingConfig)
    with app.app_context():
        db.drop_all()
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def users(app):
    """Two clinics (tenants) plus a super admin."""
    return {
        "a": create_user("clinic-a", PASSWORD, role="admin"),
        "b": create_user("clinic-b", PASSWORD, role="admin"),
        "staff": create_user("staff-a", PASSWORD, role="staff"),
        "root": create_user("root", PASSWORD, role="super_admin"),
    }


class _IsolatedClient:
    """The fixtures keep one app context open for direct DB access, so Flask reuses it (and ``g``)
    for every request. Reset the per-request CSRF cache so each request behaves like a fresh one."""

    def __init__(self, client):
        self._client = client

    def __getattr__(self, name):
        attr = getattr(self._client, name)
        if name in {"get", "post", "put", "delete", "open"}:

            def wrapper(*args, **kwargs):
                g.pop("csrf_token", None)
                return attr(*args, **kwargs)

            return wrapper
        return attr


class Browser:
    """Tiny helper that keeps cookies and handles CSRF tokens like a real browser."""

    def __init__(self, app):
        self.client = _IsolatedClient(app.test_client())

    def token(self, path="/login"):
        html = self.client.get(path, follow_redirects=True).get_data(as_text=True)
        match = re.search(r'name="csrf-token" content="([^"]+)"', html)
        assert match, "no csrf token on page"
        return match.group(1)

    def post(self, path, data=None, token=True, **kwargs):
        data = dict(data or {})
        if token is True:
            data["csrf_token"] = self.token()
        return self.client.post(path, data=data, **kwargs)

    def get(self, path, **kwargs):
        return self.client.get(path, **kwargs)

    def login(self, username, password=PASSWORD):
        return self.post("/login", {"username": username, "password": password})


@pytest.fixture()
def browser(app):
    return Browser(app)


@pytest.fixture()
def login_as(app, users):
    def _login(key):
        b = Browser(app)
        resp = b.login(users[key].username)
        assert resp.status_code == 302, resp.get_data(as_text=True)
        return b

    return _login
