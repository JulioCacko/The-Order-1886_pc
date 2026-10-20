"""Every option kind in FIELDS must have a worker validator branch.

A kind with no branch is accepted without inspection: the setting would be saved whatever the
frontend or a direct caller sent, which is the same failure shape as a control that never
reaches the backend.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / 'launcher/order1886_worker.py'


def validate_patch_source():
    text = WORKER.read_text(encoding='utf-8')
    start = text.index('def validate_patch(')
    end = text.index('\nclass Worker', start)
    return text[start:end]


def handled_kinds():
    source = validate_patch_source()
    kinds = set(re.findall(r'kind == "(\w+)"', source))
    for group in re.findall(r'kind in \(([^)]*)\)', source):
        kinds |= set(re.findall(r'"(\w+)"', group))
    return kinds


class FieldKindCoverageTests(unittest.TestCase):
    def test_every_field_kind_is_validated(self):
        from launcher.order1886_options import FIELDS
        kinds = {field['kind'] for field in FIELDS}
        missing = sorted(kinds - handled_kinds())
        self.assertFalse(missing, f'no validator branch for kinds: {missing}')

    def test_the_scan_finds_the_branches_it_should(self):
        kinds = handled_kinds()
        for expected in ('select', 'boolean', 'number', 'directory', 'file', 'text', 'order',
                         'bindings', 'patches'):
            self.assertIn(expected, kinds)

    def test_no_field_kind_is_invented_without_a_choice_list(self):
        # A select without choices renders as an empty control; a number without bounds cannot
        # be validated. Both are silent UI defects, so pin the shape.
        from launcher.order1886_options import FIELDS
        for field in FIELDS:
            with self.subTest(key=field['key']):
                if field['kind'] == 'select':
                    self.assertTrue(field.get('choices'), 'a select needs choices')
                if field['kind'] == 'number':
                    self.assertIsInstance(field.get('minimum'), int)
                    self.assertIsInstance(field.get('maximum'), int)
                    self.assertLess(field['minimum'], field['maximum'])
                if not field['available']:
                    self.assertTrue(field.get('reason'), 'unavailable needs a reason')

    def test_the_coverage_check_would_catch_a_new_unvalidated_kind(self):
        # Prove the first test bites rather than trusting that it does.
        from launcher import order1886_options
        original = list(order1886_options.FIELDS)
        try:
            order1886_options.FIELDS.append(dict(original[0], key='invented', kind='slider'))
            kinds = {field['kind'] for field in order1886_options.FIELDS}
            self.assertIn('slider', kinds - handled_kinds())
        finally:
            order1886_options.FIELDS[:] = original


class FrontendFieldKeyTests(unittest.TestCase):
    def test_every_frontend_setting_lookup_uses_a_real_field_key(self):
        from launcher.order1886_options import FIELDS
        known = {field['key'] for field in FIELDS} | {'page', 'title', 'kind'}
        frontend = ROOT / 'launcher-go/frontend/src'
        used = set()
        for path in frontend.rglob('*.ts'):
            text = path.read_text(encoding='utf-8')
            used |= set(re.findall(r'data-setting="([\w.]+)"', text))
            used |= set(re.findall(r"field\.key\s*===\s*'([\w.]+)'", text))
        unknown = sorted(used - known)
        self.assertFalse(unknown, f'the frontend references unknown field keys: {unknown}')


if __name__ == '__main__':
    unittest.main()
