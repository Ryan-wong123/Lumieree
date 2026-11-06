"""Liveness / readiness probes for Kubernetes (no authentication, no patient data)."""

from flask import Blueprint, jsonify
from sqlalchemy import text

from ..extensions import db

bp = Blueprint("health", __name__)


@bp.get("/healthz")
def healthz():
    return jsonify(status="ok")


@bp.get("/readyz")
def readyz():
    try:
        db.session.execute(text("SELECT 1"))
    except Exception:
        return jsonify(status="database unavailable"), 503
    return jsonify(status="ready")
