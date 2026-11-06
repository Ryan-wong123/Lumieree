"""Authentication, session handling and role-based access control."""

from __future__ import annotations

import re
from functools import wraps

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import func

from .extensions import db, limiter
from .models import User, utcnow
from .utils import ValidationError, clean, is_safe_next

bp = Blueprint("auth", __name__)

# Endpoints reachable without a session.
OPEN_ENDPOINTS = {"auth.login", "i18n.switch_language", "health.healthz", "health.readyz", "static"}

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,62}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Used to burn comparable CPU time when the username is unknown (anti-enumeration).
_DUMMY_HASH = None


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        from werkzeug.security import generate_password_hash

        _DUMMY_HASH = generate_password_hash("not-a-real-password")
    return _DUMMY_HASH


# ---------------------------------------------------------------- validation
def normalize_username(value: str) -> str:
    username = clean(value, 64).lower()
    if not USERNAME_RE.match(username):
        raise ValidationError("Username must be 2-64 characters: letters, numbers, '.', '_' or '-'.")
    return username


def normalize_email(value: str | None) -> str | None:
    email = clean(value, 255).lower()
    if not email:
        return None
    if not EMAIL_RE.match(email):
        raise ValidationError("Invalid email address.")
    return email


def validate_password(password: str, username: str = "") -> None:
    minimum = current_app.config["MIN_PASSWORD_LENGTH"]
    if len(password or "") < minimum:
        raise ValidationError(f"Password must be at least {minimum} characters.")
    if len(password) > 256:
        raise ValidationError("Password is too long.")
    if username and password.lower() == username.lower():
        raise ValidationError("Password must not be the same as the username.")


def create_user(username, password, role="staff", email=None, created_by=None, must_change_password=False) -> User:
    username = normalize_username(username)
    email = normalize_email(email)
    validate_password(password, username)
    if role not in ("staff", "admin", "super_admin"):
        raise ValidationError("Invalid role.")
    if db.session.execute(db.select(User).where(User.username == username)).first():
        raise ValidationError("That username is already taken.")
    if email and db.session.execute(db.select(User).where(func.lower(User.email) == email)).first():
        raise ValidationError("That email is already in use.")
    user = User(
        username=username,
        email=email,
        role=role,
        created_by_id=created_by.id if created_by else None,
        must_change_password=must_change_password,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


# ------------------------------------------------------------- session loading
def current_uid() -> int:
    """Id of the logged-in account (the tenant). Only valid inside an authenticated request."""
    return g.user.id


def init_app(app):
    app.register_blueprint(bp)

    @app.before_request
    def _load_user():
        g.user = None
        uid, version = session.get("uid"), session.get("sv")
        if uid is not None:
            user = db.session.get(User, uid)
            # Re-check the database every request: deactivation, demotion and
            # password changes take effect immediately.
            if user and user.active and user.session_version == version:
                g.user = user
            else:
                session.pop("uid", None)
                session.pop("sv", None)

        if request.endpoint is None or request.endpoint in OPEN_ENDPOINTS:
            return None
        if g.user is None:
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        if g.user.must_change_password and request.endpoint not in {"auth.settings", "auth.logout"}:
            flash("Please set a new password to continue.")
            return redirect(url_for("auth.settings"))
        return None

    @app.context_processor
    def _inject_user():
        return {"current_user": g.get("user")}


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.get("user") is None:
                return redirect(url_for("auth.login"))
            if g.user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


admin_required = roles_required("admin", "super_admin")
super_admin_required = roles_required("super_admin")


# --------------------------------------------------------------------- routes
@bp.route("/login", methods=["GET", "POST"])
@limiter.limit(lambda: current_app.config["LOGIN_RATE_LIMIT"], methods=["POST"])
def login():
    if g.get("user"):
        return redirect(url_for("patients.list_patients"))

    if request.method == "POST":
        username = clean(request.form.get("username"), 64).lower()
        password = request.form.get("password") or ""
        user = db.session.execute(db.select(User).where(User.username == username)).scalar_one_or_none()

        if user is None:
            from werkzeug.security import check_password_hash

            check_password_hash(_dummy_hash(), password)
            ok = False
        else:
            ok = user.check_password(password)

        if ok and user.active:
            nxt = request.args.get("next")
            lang = session.get("lang")
            session.clear()  # prevent session fixation
            if lang:
                session["lang"] = lang
            session["uid"] = user.id
            session["sv"] = user.session_version
            session.permanent = True
            user.last_login_at = utcnow()
            db.session.commit()
            current_app.logger.info("login ok user=%s", user.username)
            if is_safe_next(nxt):
                return redirect(nxt)
            if user.is_super_admin:
                return redirect(url_for("admin.users"))
            return redirect(url_for("patients.list_patients"))

        current_app.logger.warning("login failed username=%s ip=%s", username[:64], request.remote_addr)
        # One generic message for wrong password, unknown user and disabled account.
        flash("❌ Invalid credentials.")

    return render_template("login.html")


@bp.get("/logout")
def logout():
    # Logging out is harmless to trigger cross-site, so GET is acceptable here.
    lang = session.get("lang")
    session.clear()
    if lang:
        session["lang"] = lang
    return redirect(url_for("auth.login"))


@bp.route("/settings", methods=["GET", "POST"])
def settings():
    user = g.user
    if request.method == "POST":
        try:
            new_email = normalize_email(request.form.get("new_email"))
            new_password = request.form.get("new_password") or ""
            current_password = request.form.get("current_password") or ""

            if new_email or new_password:
                if not user.check_password(current_password):
                    raise ValidationError("Current password is incorrect.")

            if new_email:
                clash = db.session.execute(
                    db.select(User).where(func.lower(User.email) == new_email, User.id != user.id)
                ).first()
                if clash:
                    raise ValidationError("That email is already in use.")
                user.email = new_email
            if new_password:
                validate_password(new_password, user.username)
                user.set_password(new_password)
                user.must_change_password = False
            db.session.commit()
            session["sv"] = user.session_version  # keep this browser logged in
            flash("✅ Account updated successfully.")
        except ValidationError as exc:
            db.session.rollback()
            flash(f"❌ {exc}")
    return render_template("settings.html")
