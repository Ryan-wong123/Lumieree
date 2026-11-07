"""Authentication, session handling and role-based access control."""

from __future__ import annotations

import re
import time
from functools import wraps

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import func

from . import audit, mfa
from .extensions import db, limiter
from .models import User, utcnow
from .utils import ValidationError, clean, is_safe_next

bp = Blueprint("auth", __name__)

# Endpoints reachable without a session.
OPEN_ENDPOINTS = {"auth.login", "auth.login_mfa", "i18n.switch_language", "health.healthz", "health.readyz", "static"}

# After the password step, the second factor must be supplied within this time and in at most this many tries.
MFA_PENDING_SECONDS = 300
MFA_MAX_ATTEMPTS = 5

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
def _reset_session_keeping_language() -> None:
    lang = session.get("lang")
    session.clear()  # prevents session fixation and drops any half-finished login
    if lang:
        session["lang"] = lang


def _finish_login(user: User, nxt: str | None):
    """Create the authenticated session (after the password and, if enabled, the second factor)."""
    _reset_session_keeping_language()
    session["uid"] = user.id
    session["sv"] = user.session_version
    session.permanent = True
    user.last_login_at = utcnow()
    db.session.commit()
    audit.record("auth.login", actor=user)
    current_app.logger.info("login ok user=%s", user.username)
    if is_safe_next(nxt):
        return redirect(nxt)
    if user.is_super_admin:
        return redirect(url_for("admin.users"))
    return redirect(url_for("patients.list_patients"))


def _begin_mfa(user: User, nxt: str | None):
    """Password was correct but a second factor is required: park the login in the session."""
    _reset_session_keeping_language()
    session["mfa_uid"] = user.id
    session["mfa_sv"] = user.session_version
    session["mfa_exp"] = int(time.time()) + MFA_PENDING_SECONDS
    session["mfa_fail"] = 0
    if is_safe_next(nxt):
        session["mfa_next"] = nxt
    return redirect(url_for("auth.login_mfa"))


def _pending_mfa_user() -> User | None:
    uid = session.get("mfa_uid")
    if uid is None or int(time.time()) > int(session.get("mfa_exp", 0)):
        return None
    user = db.session.get(User, uid)
    if user and user.active and user.mfa_enabled and user.session_version == session.get("mfa_sv"):
        return user
    return None


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
            if user.mfa_enabled:
                return _begin_mfa(user, nxt)
            return _finish_login(user, nxt)

        current_app.logger.warning("login failed username=%s ip=%s", username[:64], request.remote_addr)
        # The attempted name is only stored when it belongs to a real account (people sometimes type their
        # password into the username box).
        reason = "unknown user" if user is None else ("disabled account" if not user.active else "wrong password")
        audit.record("auth.login_failed", actor=user, detail=reason)
        # One generic message for wrong password, unknown user and disabled account.
        flash("❌ Invalid credentials.")

    return render_template("login.html")


@bp.route("/login/mfa", methods=["GET", "POST"])
@limiter.limit(lambda: current_app.config["LOGIN_RATE_LIMIT"], methods=["POST"])
def login_mfa():
    if g.get("user"):
        return redirect(url_for("patients.list_patients"))
    user = _pending_mfa_user()
    if user is None:
        _reset_session_keeping_language()
        flash("Your sign-in expired. Please sign in again.")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        code = request.form.get("code")
        step = mfa.verify(user.totp_secret, code, user.mfa_last_step)
        if step is not None:
            user.mfa_last_step = step
            return _finish_login(user, session.get("mfa_next"))
        remaining = mfa.consume_backup_code(user.mfa_backup_codes, code)
        if remaining is not None:
            user.mfa_backup_codes = remaining
            db.session.commit()
            audit.record("auth.mfa_backup_used", actor=user, detail=f"{len(remaining)} codes left")
            return _finish_login(user, session.get("mfa_next"))

        failures = int(session.get("mfa_fail", 0)) + 1
        session["mfa_fail"] = failures
        audit.record("auth.mfa_failed", actor=user)
        if failures >= MFA_MAX_ATTEMPTS:
            _reset_session_keeping_language()
            flash("❌ Too many wrong codes. Please sign in again.")
            return redirect(url_for("auth.login"))
        flash("❌ Invalid code.")

    return render_template("login_mfa.html")


@bp.get("/logout")
def logout():
    # Logging out is harmless to trigger cross-site, so GET is acceptable here.
    if g.get("user"):
        audit.record("auth.logout")
    _reset_session_keeping_language()
    return redirect(url_for("auth.login"))


def _qr_data_uri(text: str) -> str:
    import segno

    return segno.make(text, error="m").svg_data_uri(scale=5, border=2)


@bp.route("/settings", methods=["GET", "POST"])
def settings():
    user = g.user
    if request.method == "POST":
        events = []
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
                events.append("auth.email_changed")
            if new_password:
                validate_password(new_password, user.username)
                user.set_password(new_password)
                user.must_change_password = False
                events.append("auth.password_changed")
            db.session.commit()
            session["sv"] = user.session_version  # keep this browser logged in
            for event in events:
                audit.record(event)
            flash("✅ Account updated successfully.")
        except ValidationError as exc:
            db.session.rollback()
            flash(f"❌ {exc}")

    context = {}
    setup_secret = None if user.mfa_enabled else session.get("mfa_setup_secret")
    if setup_secret:
        context["mfa_secret"] = setup_secret
        context["mfa_qr"] = _qr_data_uri(mfa.provisioning_uri(user.username, setup_secret))
    return render_template("settings.html", **context)


@bp.post("/settings/mfa/start")
def mfa_start():
    if g.user.mfa_enabled:
        flash("Two-factor authentication is already on.")
    else:
        session["mfa_setup_secret"] = mfa.new_secret()
    return redirect(url_for("auth.settings"))


@bp.post("/settings/mfa/enable")
@limiter.limit(lambda: current_app.config["LOGIN_RATE_LIMIT"])
def mfa_enable():
    user = g.user
    secret = session.get("mfa_setup_secret")
    if user.mfa_enabled or not secret:
        return redirect(url_for("auth.settings"))
    step = mfa.verify(secret, request.form.get("code"))
    if step is None:
        flash("❌ That code is not valid. Check the 6-digit code in your authenticator app and try again.")
        return redirect(url_for("auth.settings"))
    codes, hashes = mfa.new_backup_codes()
    user.totp_secret = secret
    user.mfa_enabled = True
    user.mfa_last_step = step
    user.mfa_backup_codes = hashes
    user.session_version += 1  # signs out any other browser; this one is re-synced below
    db.session.commit()
    session.pop("mfa_setup_secret", None)
    session["sv"] = user.session_version
    audit.record("auth.mfa_enabled")
    return render_template("mfa_backup_codes.html", codes=codes)


@bp.post("/settings/mfa/disable")
@limiter.limit(lambda: current_app.config["LOGIN_RATE_LIMIT"])
def mfa_disable():
    user = g.user
    if not user.mfa_enabled:
        return redirect(url_for("auth.settings"))
    code = request.form.get("code")
    code_ok = (
        mfa.verify(user.totp_secret, code, user.mfa_last_step) is not None
        or mfa.consume_backup_code(user.mfa_backup_codes, code) is not None
    )
    if not user.check_password(request.form.get("current_password") or "") or not code_ok:
        audit.record("auth.mfa_disable_failed")
        flash("❌ Password or code is incorrect.")
        return redirect(url_for("auth.settings"))
    user.mfa_enabled = False
    user.totp_secret = None
    user.mfa_last_step = None
    user.mfa_backup_codes = []
    user.session_version += 1
    db.session.commit()
    session["sv"] = user.session_version
    audit.record("auth.mfa_disabled")
    flash("Two-factor authentication turned off.")
    return redirect(url_for("auth.settings"))
