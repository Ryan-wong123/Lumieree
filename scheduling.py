"""Appointment scheduling rules shared by HTTP handlers and tests.

All persisted appointment instants are UTC ISO strings.  Local dates and times are
accepted only together with an explicit IANA clinic timezone.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class SchedulingError(ValueError):
    pass


def clinic_zone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, TypeError):
        raise SchedulingError("The clinic timezone is invalid.")


def local_slot(date_text, time_text, duration_minutes, timezone_name):
    try:
        duration = int(duration_minutes)
        naive = datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        raise SchedulingError("Enter a valid appointment date, time, and duration.")
    if duration < 5 or duration > 480 or duration % 5:
        raise SchedulingError("Service duration must be 5–480 minutes in 5-minute increments.")
    start = naive.replace(tzinfo=clinic_zone(timezone_name))
    # Round-tripping detects nonexistent wall times at daylight-saving transitions.
    if start.astimezone(timezone.utc).astimezone(start.tzinfo).replace(fold=start.fold) != start:
        raise SchedulingError("That local time does not exist in the clinic timezone.")
    return start, start + timedelta(minutes=duration)


def utc_iso(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(value):
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def overlaps(start, end, other_start, other_end):
    """Half-open intervals permit adjacent appointments."""
    return start < other_end and other_start < end


def can_manage(role, appointment_owner, clinic_owner, appointment_patient, linked_patient, staff_roles):
    if appointment_owner != clinic_owner:
        return False
    return role in staff_roles or (role == "patient" and bool(linked_patient) and appointment_patient == linked_patient)


def is_available(start_local, end_local, weekly_schedule):
    periods = weekly_schedule.get(str(start_local.weekday()), [])
    if start_local.date() != (end_local - timedelta(microseconds=1)).date():
        return False
    start_hm, end_hm = start_local.strftime("%H:%M"), end_local.strftime("%H:%M")
    return any(p.get("start", "") <= start_hm and end_hm <= p.get("end", "") for p in periods)


def lock_keys(practitioner_id, start, end, increment=5):
    """Deterministic lock keys make simultaneous overlapping writes contend."""
    cursor = start.astimezone(timezone.utc)
    keys = []
    while cursor < end.astimezone(timezone.utc):
        keys.append(f"{practitioner_id}_{cursor.strftime('%Y%m%dT%H%MZ')}")
        cursor += timedelta(minutes=increment)
    return keys


def available_slots(day, duration, timezone_name, weekly_schedule, booked_intervals, increment=15):
    zone = clinic_zone(timezone_name)
    weekday = datetime.strptime(day, "%Y-%m-%d").weekday()
    result = []
    for period in weekly_schedule.get(str(weekday), []):
        cursor, _ = local_slot(day, period["start"], duration, timezone_name)
        period_end, _ = local_slot(day, period["end"], 5, timezone_name)
        while cursor + timedelta(minutes=int(duration)) <= period_end:
            end = cursor + timedelta(minutes=int(duration))
            if not any(overlaps(cursor, end, a, b) for a, b in booked_intervals):
                result.append(cursor.strftime("%H:%M"))
            cursor += timedelta(minutes=increment)
    return result
