"""Lumieree – multi-tenant TCM clinic POS (Flask + PostgreSQL)."""

from __future__ import annotations

import logging
import os
import sqlite3
import sys

from flask import Flask, jsonify, render_template, request
from sqlalchemy import event
from sqlalchemy.engine import Engine
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from . import auth, i18n
from .config import Config, validate
from .extensions import csrf, db, limiter, migrate


@event.listens_for(Engine, "connect")
def _sqlite_enforce_foreign_keys(dbapi_connection, _record):
    """SQLite ignores foreign keys unless asked (used by unit tests; Postgres always enforces them)."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


CSP = "; ".join(
    [
        "default-src 'self'",
        # Templates still contain inline <script>/<style>; tighten with nonces when they are extracted.
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com",
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
        "font-src 'self' https://cdn.jsdelivr.net",
        "img-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)


def create_app(config_object=None) -> Flask:
    app = Flask(__name__, template_folder="../templates", static_folder="../static", static_url_path="/static")
    app.config.from_object(config_object or Config)
    validate(app.config)

    _configure_logging(app)

    if app.config["TRUSTED_PROXY_COUNT"] > 0:
        n = app.config["TRUSTED_PROXY_COUNT"]
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=n, x_host=n)

    db.init_app(app)
    migrate.init_app(app, db, directory=os.path.join(os.path.dirname(__file__), "..", "migrations"))
    csrf.init_app(app)
    limiter.init_app(app)

    from . import models  # noqa: F401  (register tables)
    from .blueprints import admin, appointments, front_desk, health, inventory, patients, receipts

    i18n.init_app(app)
    auth.init_app(app)
    for module in (health, inventory, patients, front_desk, receipts, admin, appointments):
        app.register_blueprint(module.bp)

    @app.get("/")
    def home():
        from flask import redirect, url_for

        return redirect(url_for("patients.list_patients"))

    _register_hooks(app)

    from .cli import register_cli

    register_cli(app)
    return app


def _configure_logging(app: Flask) -> None:
    if app.testing:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(handler)
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())


def _register_hooks(app: Flask) -> None:
    @app.context_processor
    def _inject_now():
        from datetime import datetime

        return {"now": datetime.now}

    @app.after_request
    def _security_headers(response):
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
        if app.config["SESSION_COOKIE_SECURE"]:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        # Pages contain patient data: never let shared caches store them.
        if request.endpoint != "static":
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    def _wants_json() -> bool:
        return request.path.startswith("/api/") or request.path in {"/appointments/json", "/appointments/event_counts"}

    @app.errorhandler(HTTPException)
    def _http_error(exc: HTTPException):
        if _wants_json():
            return jsonify(error=exc.name), exc.code
        return render_template("error.html", code=exc.code, title=exc.name, message=exc.description), exc.code

    @app.errorhandler(Exception)
    def _unhandled(exc: Exception):
        app.logger.exception("Unhandled error")
        db.session.rollback()
        if _wants_json():
            return jsonify(error="Internal Server Error"), 500
        return render_template("error.html", code=500, title="Server error", message="Something went wrong."), 500

    @app.teardown_appcontext
    def _shutdown_session(exc):
        db.session.remove()
