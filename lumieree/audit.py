"""Append-only audit trail: who did what, to which record, from where."""

from __future__ import annotations

from flask import g, has_request_context, request

from .extensions import db
from .models import AuditLog, User
from .utils import clean


def record(
    action: str,
    *,
    target_type: str | None = None,
    target_id: int | None = None,
    detail: str | None = None,
    actor: User | None = None,
    owner_id: int | None = None,
    commit: bool = True,
) -> None:
    """Add one audit row.

    ``actor`` defaults to the logged-in user and ``owner_id`` (the tenant whose data is touched) to the actor.
    ``commit=True`` commits immediately: call it after your own commit, or when nothing else is pending.
    Never pass secrets, passwords or free-text patient data in ``detail``.
    """
    user = actor if actor is not None else g.get("user")
    entry = AuditLog(
        actor_id=user.id if user else None,
        actor_username=user.username if user else None,
        owner_id=owner_id if owner_id is not None else (user.id if user else None),
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=clean(detail, 255) or None,
        ip=(clean(request.remote_addr, 45) or None) if has_request_context() else None,
    )
    db.session.add(entry)
    if commit:
        db.session.commit()
