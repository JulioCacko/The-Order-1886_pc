"""HTILE control stays off unless a matching runtime declares it and the player opts in."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import order1886
from launcher import order1886_common as launcher
from launcher import order1886_worker as worker

ROOT = Path(__file__).resolve().parents[1]


def runtime_with(state, **build):
    runtime = state / 'runtime.exe'
    runtime.write_bytes(b'native fixture')
    receipt = {'runtime_sha256': hashlib.sha256(runtime.read_bytes()).hexdigest(),
               'game_profile': 'order1886', 'runtime_abi': order1886.RUNTIME_ABI}
    receipt.update(build)
    runtime.with_name('runtime-build.json').write_text(json.dumps(receipt))
    return runtime


class HtileControlTests(unittest.TestCase):
    def test_default_is_off_in_the_launch_environment(self):
        env = order1886.runtime_environment(ROOT / 'out' / 'runtime.exe', ROOT / 'out' / 'state', {}, {})
        self.assertEqual(env['ORDER1886_HTILE'], '0')

    def test_declared_runtime_can_enable_htile_and_env_follows(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            runtime = runtime_with(state, htile_control=True)
            env = order1886.runtime_environment(runtime, state, {'htile_unqualified': True}, {})
            self.assertEqual(env['ORDER1886_HTILE'], '1')
            env = order1886.runtime_environment(runtime, state, {'htile_unqualified': False}, {})
            self.assertEqual(env['ORDER1886_HTILE'], '0')

    def test_runtime_without_the_declaration_refuses_the_option(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            runtime = runtime_with(state)
            with self.assertRaises(ValueError) as raised:
                order1886.runtime_environment(runtime, state, {'htile_unqualified': True}, {})
            self.assertIn('HTILE control requires', str(raised.exception))
            env = order1886.runtime_environment(runtime, state, {'htile_unqualified': False}, {})
            self.assertEqual(env['ORDER1886_HTILE'], '0')

    def test_invalid_values_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            runtime = runtime_with(state, htile_control=True)
            for invalid in ('on', 2, None, [True]):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    order1886.runtime_environment(runtime, state, {'htile_unqualified': invalid}, {})

    def test_catalog_exposes_the_option_off_by_default(self):
        field = next(item for item in worker.FIELDS if item['key'] == 'htile_unqualified')
        self.assertEqual(field['default'], False)
        self.assertEqual(field['kind'], 'boolean')
        self.assertEqual(field['page'], 'performance')
        self.assertTrue(field['available'])
        self.assertIn('qualification', field['description'].lower())

    def test_setting_round_trips_through_the_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            runtime = runtime_with(state, htile_control=True)
            app = worker.Worker(state, ROOT)
            app.dispatch('settings.set', {'values': {'runtime': str(runtime)}})
            values = app.dispatch('settings.set', {'values': {'htile_unqualified': True}})['settings']
            self.assertIs(values['htile_unqualified'], True)
            values = app.dispatch('settings.set', {'values': {'htile_unqualified': False}})['settings']
            self.assertIs(values['htile_unqualified'], False)

    def test_worker_refuses_the_option_for_a_runtime_without_the_declaration(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            runtime = runtime_with(state)
            app = worker.Worker(state, ROOT)
            app.dispatch('settings.set', {'values': {'runtime': str(runtime)}})
            with self.assertRaises(ValueError):
                app.dispatch('settings.set', {'values': {'htile_unqualified': True}})
            values = app.dispatch('state.get', {})['settings']
            self.assertIs(values['htile_unqualified'], False)


if __name__ == '__main__':
    unittest.main()
