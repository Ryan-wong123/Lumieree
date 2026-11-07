"""Small, dependency-free helpers shared by the blueprints."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse


class ValidationError(ValueError):
    """Raised for bad user input; the message is safe to flash to the user."""


def clean(value, max_len: int = 500) -> str:
    return (str(value).strip() if value is not None else "")[:max_len]


MAX_MONEY = Decimal("99999999.99")  # fits Numeric(10, 2)
MAX_INT = 1_000_000_000


def to_decimal(value, default: Decimal | None = None, *, minimum: Decimal | None = Decimal("0")) -> Decimal:
    try:
        number = Decimal(str(value).strip())
        if not number.is_finite():
            raise InvalidOperation
    except (InvalidOperation, ValueError, TypeError):
        if default is not None:
            return default
        raise ValidationError("Invalid number.") from None
    if (minimum is not None and number < minimum) or number > MAX_MONEY:
        if default is not None:
            return default
        raise ValidationError("Amount is out of range.")
    return number.quantize(Decimal("0.01"))


def to_int(value, default: int | None = None, *, minimum: int | None = 0) -> int:
    try:
        number = int(Decimal(str(value).strip()))
    except (InvalidOperation, ValueError, TypeError):
        if default is not None:
            return default
        raise ValidationError("Invalid whole number.") from None
    if (minimum is not None and number < minimum) or number > MAX_INT:
        if default is not None:
            return default
        raise ValidationError("Number is out of range.")
    return number


def parse_date(value) -> date | None:
    """Accept YYYY-MM-DD (optionally with a time part) or D/M/YYYY. Returns None if blank/invalid."""
    s = clean(value, 40)
    if not s:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def today() -> date:
    return datetime.now().date()


_CSV_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value):
    """Neutralise spreadsheet formula injection in exported cells."""
    if isinstance(value, str) and value.startswith(_CSV_DANGEROUS):
        return "'" + value
    return value


def is_safe_next(target: str | None) -> bool:
    """Only allow same-site relative redirects (prevents open redirects)."""
    if not target:
        return False
    parsed = urlparse(target)
    return (
        not parsed.scheme
        and not parsed.netloc
        and target.startswith("/")
        and not target.startswith("//")
        and "\\" not in target
    )
