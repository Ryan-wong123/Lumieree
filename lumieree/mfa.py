"""Time-based one-time passwords (RFC 6238) and recovery codes, using only the standard library."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import struct
import time
from urllib.parse import quote

STEP_SECONDS = 30
DIGITS = 6
WINDOW = 1  # accept the previous, current and next 30-second step (clock drift)
ISSUER = "Lumieree"
BACKUP_CODE_COUNT = 8


def new_secret() -> str:
    """160-bit random secret, base32 without padding (what authenticator apps expect)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _code_for_step(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()  # noqa: S324 (mandated by RFC 6238)
    offset = digest[-1] & 0x0F
    value = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 10**DIGITS
    return f"{value:0{DIGITS}d}"


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP_SECONDS)


def code_at(secret: str, now: float | None = None) -> str:
    """The code valid right now (used by tests and for self-checks)."""
    return _code_for_step(secret, current_step(now))


def verify(secret: str, code: str | None, last_step: int | None = None, now: float | None = None) -> int | None:
    """Return the matching time step, or None.

    Steps at or before ``last_step`` are refused, so a code (or a shoulder-surfed one) works only once.
    """
    code = re.sub(r"\s+", "", code or "")
    if not re.fullmatch(rf"\d{{{DIGITS}}}", code):
        return None
    step = current_step(now)
    for candidate in range(step - WINDOW, step + WINDOW + 1):
        if last_step is not None and candidate <= last_step:
            continue
        if hmac.compare_digest(_code_for_step(secret, candidate), code):
            return candidate
    return None


def provisioning_uri(username: str, secret: str) -> str:
    label = f"{quote(ISSUER)}:{quote(username)}"
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}&digits={DIGITS}&period={STEP_SECONDS}"


# ------------------------------------------------------------------ recovery codes
def _normalize_backup(code: str | None) -> str:
    return re.sub(r"[\s-]+", "", (code or "").lower())


def hash_backup_code(code: str) -> str:
    # Plain SHA-256 is adequate here: codes are random (40 bits), single-use and the endpoint is rate limited.
    return hashlib.sha256(_normalize_backup(code).encode("ascii", "ignore")).hexdigest()


def new_backup_codes() -> tuple[list[str], list[str]]:
    """Return (codes to show the user once, hashes to store)."""
    codes = []
    for _ in range(BACKUP_CODE_COUNT):
        raw = secrets.token_hex(5)
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes, [hash_backup_code(c) for c in codes]


def consume_backup_code(stored_hashes: list[str], code: str | None) -> list[str] | None:
    """If ``code`` matches a stored hash, return the remaining hashes (the code is spent); else None."""
    candidate = hash_backup_code(code or "")
    for h in stored_hashes or []:
        if hmac.compare_digest(h, candidate):
            return [x for x in stored_hashes if x != h]
    return None
