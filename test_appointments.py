import ast
from pathlib import Path
import unittest


APP_SOURCE = Path(__file__).with_name('app.py').read_text(encoding='utf-8')
MODULE = ast.parse(APP_SOURCE)


def load_functions(*names):
    selected = [node for node in MODULE.body
                if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {'datetime': __import__('datetime').datetime,
                 'APPOINTMENT_START_HOUR': 10, 'APPOINTMENT_END_HOUR': 20}
    exec(compile(ast.Module(body=selected, type_ignores=[]), 'app.py', 'exec'), namespace)
    return namespace


class Document:
    def __init__(self, identifier, slots):
        self.id = identifier
        self._slots = slots

    def to_dict(self):
        return {'slots': self._slots}


class AppointmentRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = load_functions('parse_appointment_date', 'parse_appointment_hour',
                                   'appointment_slot_is_booked', 'occupied_appointment_hours')

    def test_date_and_hour_validation(self):
        self.assertEqual(str(self.rules['parse_appointment_date']('2026-08-22')), '2026-08-22')
        self.assertIsNone(self.rules['parse_appointment_date']('22/08/2026'))
        self.assertEqual(self.rules['parse_appointment_hour']('10'), 10)
        self.assertIsNone(self.rules['parse_appointment_hour']('21'))

    def test_occupied_hours_ignore_blank_values(self):
        docs = [Document('a', {'10': 'consult', '11': '  '}), Document('b', {'12': 'follow-up'})]
        self.assertEqual(self.rules['occupied_appointment_hours'](docs), {10, 12})

    def test_reschedule_exclusion_only_ignores_source_slot(self):
        docs = [Document('a', {'10': 'one', '11': 'two'}), Document('b', {'12': 'three'})]
        occupied = self.rules['occupied_appointment_hours'](docs, 'a', 10)
        self.assertEqual(occupied, {11, 12})


if __name__ == '__main__':
    unittest.main()
