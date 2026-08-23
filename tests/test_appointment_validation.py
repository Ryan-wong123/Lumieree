import ast
import re
import unittest
from datetime import datetime
from pathlib import Path


APP_PATH = Path(__file__).parents[1] / 'app.py'
FUNCTIONS = {
    'parse_appointment_date',
    'parse_appointment_hour',
    'valid_appointment_id',
    'occupied_appointment_hours',
}


def load_booking_functions():
    tree = ast.parse(APP_PATH.read_text(encoding='utf-8'))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS]
    module = ast.Module(body=selected, type_ignores=[])
    namespace = {
        'datetime': datetime,
        're': re,
        'APPOINTMENT_START_HOUR': 10,
        'APPOINTMENT_END_HOUR': 20,
    }
    exec(compile(module, str(APP_PATH), 'exec'), namespace)
    return namespace


class FakeDocument:
    def __init__(self, document_id, slots):
        self.id = document_id
        self._slots = slots

    def to_dict(self):
        return {'slots': self._slots}


class AppointmentValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.functions = load_booking_functions()

    def test_date_requires_canonical_iso_value(self):
        parse = self.functions['parse_appointment_date']
        self.assertEqual(parse('2026-08-23').isoformat(), '2026-08-23')
        self.assertIsNone(parse('23/08/2026'))
        self.assertIsNone(parse('2026-02-30'))

    def test_hour_is_limited_to_supported_schedule(self):
        parse = self.functions['parse_appointment_hour']
        self.assertEqual(parse('10'), 10)
        self.assertEqual(parse(20), 20)
        self.assertIsNone(parse('9'))
        self.assertIsNone(parse('not-an-hour'))

    def test_document_identifier_validation(self):
        valid = self.functions['valid_appointment_id']
        self.assertTrue(valid('abc_123-Z'))
        self.assertFalse(valid('../other-tenant'))
        self.assertFalse(valid(''))

    def test_conflicts_ignore_empty_and_explicitly_excluded_slots(self):
        occupied = self.functions['occupied_appointment_hours']
        occupied.__globals__['appointment_documents_for_date'] = lambda _date: [
            FakeDocument('first', {'10': 'Consultation', '11': ''}),
            FakeDocument('second', {'12': 'Acupuncture'}),
        ]
        self.assertEqual(occupied('2026-08-23'), {10, 12})
        self.assertEqual(occupied('2026-08-23', {('first', '10')}), {12})

    def test_booking_routes_apply_appointment_authorization(self):
        tree = ast.parse(APP_PATH.read_text(encoding='utf-8'))
        protected = {
            'appointments_combined', 'save_appointments', 'appointments_json',
            'delete_appointment', 'reschedule_appointment',
            'appointment_availability', 'appointment_event_counts',
        }
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        for name in protected:
            calls = [node for node in ast.walk(functions[name]) if isinstance(node, ast.Call)]
            self.assertTrue(
                any(isinstance(call.func, ast.Name) and call.func.id == 'require_appointment_access'
                    for call in calls),
                f'{name} must enforce appointment authorization',
            )


if __name__ == '__main__':
    unittest.main()
