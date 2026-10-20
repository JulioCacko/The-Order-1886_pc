"""Every launcher setting the backend consumes must travel on the command line.

Three settings shipped inert because the backend reads them from the settings mapping while
the CLI had no flag for them and `backend_command` never passed one: `fps_cap`,
`htile_unqualified` and `in_game_menu`. The launcher showed a control, the backend used its
default, and nothing failed. This table is the contract that stops that happening again.
"""
from pathlib import Path
import hashlib
import json
import tempfile
import unittest

import order1886
from launcher import order1886_launcher as launcher

ROOT = Path(__file__).resolve().parents[1]

# setting -> (flag, on value, off value, style)
#   'value'  : the flag is always carried with its value (off value included)
#   'switch' : the flag is a store_true switch and is omitted when off
PLUMBING = {
    'fps_cap': ('--fps-cap', 90, 120, 'value'),
    'frame_rate': ('--frame-rate', 60, 30, 'value'),
    'readbacks': ('--readbacks', 'selective', 'relaxed', 'value'),
    'aspect_ratio': ('--aspect-ratio', '16:9', 'original', 'value'),
    'performance_capture': ('--performance-capture', 1, 0, 'value'),
    'mouse_look': ('--mouse-look', 0, 1, 'value'),
    'mouse_sensitivity': ('--mouse-sensitivity', 250, 100, 'value'),
    'mouse_invert_y': ('--mouse-invert-y', 1, 0, 'value'),
    'htile_unqualified': ('--htile', True, False, 'switch'),
    'in_game_menu': ('--in-game-menu', True, False, 'switch'),
    'synchronous_recording': ('--synchronous-recording', True, False, 'switch'),
    'texture_update_locking': ('--texture-update-locking', True, False, 'switch'),
}


def values(**overrides):
    base = {'game_dir': 'game', 'display_mode': 'windowed', 'vsync': True, 'show_fps': False,
            'frame_rate': 30, 'aspect_ratio': 'original', 'mouse_look': True,
            'mouse_sensitivity': 100, 'mouse_invert_y': False, 'readbacks': 'relaxed',
            'performance_capture': False, 'fps_cap': 120, 'htile_unqualified': False,
            'in_game_menu': False, 'synchronous_recording': False,
            'texture_update_locking': False}
    base.update(overrides)
    return base


def runtime_with(state, **build):
    runtime = state / 'runtime.exe'
    runtime.write_bytes(b'native fixture')
    receipt = {'runtime_sha256': hashlib.sha256(runtime.read_bytes()).hexdigest(),
               'game_profile': 'order1886', 'runtime_abi': order1886.RUNTIME_ABI}
    receipt.update(build)
    runtime.with_name('runtime-build.json').write_text(json.dumps(receipt))
    return runtime


def parsed_settings(argv):
    settings = vars(order1886.argument_parser().parse_args(argv))
    settings.update({'keyboard_bindings': {}, 'controller_bindings': {}})
    return settings


class CommandPlumbingTests(unittest.TestCase):
    def test_each_setting_reaches_the_command(self):
        flags = {option for action in order1886.argument_parser()._actions
                 for option in action.option_strings}
        for setting, (flag, on, off, style) in PLUMBING.items():
            with self.subTest(setting=setting):
                self.assertIn(flag, flags, f'{setting} has no CLI flag')
                when_on = launcher.backend_command(values(**{setting: on}), 'play')
                self.assertIn(flag, when_on)
                if style == 'value':
                    self.assertEqual(when_on[when_on.index(flag) + 1], str(on))
                when_off = launcher.backend_command(values(**{setting: off}), 'play')
                if style == 'switch':
                    self.assertNotIn(flag, when_off)
                else:
                    self.assertEqual(when_off[when_off.index(flag) + 1], str(off))

    def test_the_parsed_flags_are_the_settings_keys_the_backend_reads(self):
        # argparse dests must line up with the mapping keys runtime_environment reads, or the
        # flag arrives and is ignored.
        with tempfile.TemporaryDirectory() as temporary:
            runtime = runtime_with(Path(temporary), htile_control=True)
            env = order1886.runtime_environment(
                runtime, Path(temporary),
                parsed_settings(['--htile', '--in-game-menu', '--fps-cap', '90', '--frame-rate', '60']), {})
            self.assertEqual(env['ORDER1886_HTILE'], '1')
            self.assertEqual(env['ORDER1886_SETTINGS_MENU'], '1')
            self.assertEqual(env['ORDER1886_FPS_LIMIT'], '60')

    def test_the_off_values_keep_the_previous_behaviour(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = runtime_with(Path(temporary), htile_control=True)
            env = order1886.runtime_environment(runtime, Path(temporary), parsed_settings([]), {})
            self.assertEqual(env['ORDER1886_HTILE'], '0')
            self.assertEqual(env['ORDER1886_SETTINGS_MENU'], '0')
            self.assertEqual(env['ORDER1886_FPS_LIMIT'], '30')

    def test_an_undeclared_runtime_still_refuses_the_htile_flag(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = runtime_with(Path(temporary))
            with self.assertRaises(ValueError):
                order1886.runtime_environment(runtime, Path(temporary),
                                             parsed_settings(['--htile']), {})


if __name__ == '__main__':
    unittest.main()
