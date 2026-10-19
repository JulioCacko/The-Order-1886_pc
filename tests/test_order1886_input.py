"""Runtime input inventory and validated launcher mappings, without player input."""
from pathlib import Path
import json
import os
import subprocess
import unittest
import tempfile
import contextlib
import io
from types import SimpleNamespace
from unittest.mock import patch
import order1886
from launcher import order1886_launcher as launcher
from scripts import order1886_input as inputs

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'out/gpu' / ('pad-map-test.exe' if os.name == 'nt' else 'pad-map-test')


class InputMappingTests(unittest.TestCase):
    def test_malformed_native_inventory_is_rejected(self):
        for value in ([], {'version': True}, {'version': 1, 'unbinding': False},
                      {'version': 1, 'unbinding': True, 'keyboard_sources': ['Q', 'Q']}):
            with self.subTest(value=value), patch.object(inputs.subprocess, 'run', return_value=
                    SimpleNamespace(returncode=0, stdout=json.dumps(value).encode())):
                with self.assertRaisesRegex(ValueError, 'malformed input inventory'):
                    inputs.read_catalog('fixture-runtime', {})

    def test_malformed_cli_bindings_fail_before_preparation_or_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'state'
            for spec in ('[]', '{bad', '{"cross":false}', '{"unknown":"Q"}'):
                with self.subTest(spec=spec), patch.object(order1886, 'prepare_game') as prepare, \
                     patch.object(order1886.save_backup, 'backup') as backup, \
                     contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(order1886.main(['--state-dir', str(state), '--keyboard-bindings', spec]), 2)
                    prepare.assert_not_called()
                    backup.assert_not_called()
                    self.assertFalse(state.exists())

    def test_nonempty_maps_require_hash_matching_runtime_support_but_defaults_do_not(self):
        with patch.object(order1886, 'runtime_identity', return_value={'build': {}}):
            self.assertEqual(order1886.validate_input_settings(None, {}),
                             {'ORDER1886_KEY_MAP': '', 'ORDER1886_PAD_MAP': ''})
            with self.assertRaisesRegex(ValueError, 'matching native runtime'):
                order1886.validate_input_settings(Path('old-runtime.exe'), {'keyboard_bindings': {'cross': 'Q'}})

    def test_mapping_encoding_rejects_values_the_native_parser_would_ignore(self):
        catalog = {'keyboard_sources': ['Q', 'Space', 'Left Shift', ',', '='],
                   'unbinding': True,
                   'keyboard_scancodes': {'Q': 20, 'Space': 44, 'Left Shift': 225, ',': 54, '=': 46},
                   'controller_sources': ['a', 'b', 'guide']}
        self.assertEqual(inputs.encode({'cross': 'Q', 'triangle': 'Space'}, 'keyboard', catalog),
                         'cross=scancode:20,triangle=scancode:44')
        self.assertEqual(inputs.encode({'cross': 'b', 'circle': 'a'}, 'controller', catalog),
                         'cross=b,circle=a')
        self.assertEqual(inputs.encode({}, 'keyboard'), '')
        self.assertEqual(inputs.encode({'cross': '='}, 'keyboard', catalog), 'cross=scancode:46')
        self.assertEqual(inputs.encode({'cross': ','}, 'keyboard', catalog), 'cross=scancode:54')
        self.assertEqual(inputs.encode({'cross': inputs.UNBOUND}, 'keyboard', catalog), 'cross=none')
        for mapping in ([], None, {'cross': False}, {'cross': 'NotAKey'}, {'unknown': 'Q'},
                        {'cross': 'Q\n'}, {'cross': ''}):
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                inputs.encode(mapping, 'keyboard', catalog)



@unittest.skipUnless(NATIVE.exists(), 'build the actual SDL pad-map fixture first')
class NativeInputInventoryTests(unittest.TestCase):
    def test_saved_maps_reach_backend_and_replace_inherited_overrides(self):
        values = dict(game_dir='game', display_mode='windowed', vsync=True, show_fps=False,
                      keyboard_bindings={'cross': 'Q', 'triangle': 'Space'},
                      controller_bindings={'cross': 'b', 'circle': 'a'})
        command = launcher.backend_command(values)
        for kind in ('keyboard', 'controller'):
            self.assertEqual(json.loads(command[command.index('--' + kind + '-bindings') + 1]),
                             values[kind + '_bindings'])
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(order1886, 'runtime_identity', return_value={'build': {'input_remapping': True}}):
            environment = order1886.runtime_environment(NATIVE, Path(directory), values,
                inherited={'ORDER1886_KEY_MAP': 'cross=NotAKey', 'ORDER1886_PAD_MAP': 'cross=guide',
                           'PATH': '', 'MSYS2_ROOT': os.environ.get('MSYS2_ROOT', r'C:\msys64')})
            self.assertEqual(environment['ORDER1886_KEY_MAP'], 'cross=scancode:20,triangle=scancode:44')
            self.assertEqual(environment['ORDER1886_PAD_MAP'], 'cross=b,circle=a')

    def test_inventory_reports_actual_default_sources_and_supported_names(self):
        environment = dict(os.environ)
        if os.name == 'nt':
            dependencies = Path(environment.get('MSYS2_ROOT', r'C:\msys64')) / 'clang64/bin'
            environment['PATH'] = str(dependencies) + os.pathsep + environment.get('PATH', '')
        result = subprocess.run([str(NATIVE), '--input-options'], capture_output=True,
                                env=environment, timeout=10, check=True)
        catalog = json.loads(result.stdout)
        self.assertEqual(catalog['version'], 1)
        buttons = {row['id']: row for row in catalog['buttons']}
        self.assertEqual(len(buttons), 17)
        self.assertEqual(buttons['cross']['keyboard_default'], ['Space'])
        self.assertEqual(buttons['cross']['controller_default'], ['a'])
        self.assertEqual(buttons['touchpad_right']['keyboard_default'], ['Backspace'])
        self.assertEqual(buttons['l2']['controller_default'], [])
        self.assertIn('Q', catalog['keyboard_sources'])
        self.assertIn(',', catalog['keyboard_sources'])
        self.assertIn('Return [158]', catalog['keyboard_sources'])
        self.assertEqual(catalog['keyboard_scancodes']['Return [158]'], 158)
        self.assertIn('b', catalog['controller_sources'])
        self.assertEqual(len(catalog['keyboard_sources']), len(set(catalog['keyboard_sources'])))
        self.assertEqual(inputs.read_catalog(NATIVE, environment), catalog)
