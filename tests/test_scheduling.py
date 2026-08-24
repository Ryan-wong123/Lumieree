import unittest
from datetime import datetime, timezone

from scheduling import SchedulingError, available_slots, can_manage, is_available, local_slot, lock_keys, overlaps


SCHEDULE = {"0": [{"start": "09:00", "end": "12:00"}]}


class SchedulingTests(unittest.TestCase):
    def test_overlap_rejects_intersection_but_allows_adjacent_slots(self):
        start = datetime(2026, 8, 24, 9, tzinfo=timezone.utc)
        end = datetime(2026, 8, 24, 10, tzinfo=timezone.utc)
        self.assertTrue(overlaps(start, end, start, end))
        self.assertFalse(overlaps(start, end, end, end.replace(hour=11)))

    def test_timezone_conversion_and_schedule_boundary(self):
        start, end = local_slot("2026-08-24", "09:30", 30, "Asia/Singapore")
        self.assertEqual(start.astimezone(timezone.utc).hour, 1)
        self.assertTrue(is_available(start, end, SCHEDULE))
        late, too_late = local_slot("2026-08-24", "11:45", 30, "Asia/Singapore")
        self.assertFalse(is_available(late, too_late, SCHEDULE))

    def test_invalid_timezone_and_duration_are_rejected(self):
        with self.assertRaises(SchedulingError): local_slot("2026-08-24", "09:00", 30, "Not/AZone")
        with self.assertRaises(SchedulingError): local_slot("2026-08-24", "09:00", 31, "UTC")

    def test_slots_exclude_bookings_and_lock_keys_overlap(self):
        booked_start, booked_end = local_slot("2026-08-24", "09:30", 30, "UTC")
        slots = available_slots("2026-08-24", 30, "UTC", SCHEDULE, [(booked_start, booked_end)])
        self.assertNotIn("09:30", slots); self.assertNotIn("09:45", slots)
        first_start, first_end = local_slot("2026-08-24", "09:00", 60, "UTC")
        second_start, second_end = local_slot("2026-08-24", "09:30", 30, "UTC")
        self.assertTrue(set(lock_keys("p1", first_start, first_end)) & set(lock_keys("p1", second_start, second_end)))

    def test_permissions_enforce_clinic_and_patient_ownership(self):
        staff_roles = {'staff', 'admin'}
        self.assertTrue(can_manage('staff', 'clinic-a', 'clinic-a', 'patient-a', None, staff_roles))
        self.assertTrue(can_manage('patient', 'clinic-a', 'clinic-a', 'patient-a', 'patient-a', staff_roles))
        self.assertFalse(can_manage('patient', 'clinic-a', 'clinic-a', 'patient-b', 'patient-a', staff_roles))
        self.assertFalse(can_manage('staff', 'clinic-b', 'clinic-a', 'patient-a', None, staff_roles))


if __name__ == '__main__': unittest.main()
