"""The presentation cap the launcher shows must be the one the backend actually applies."""
from pathlib import Path
import unittest

import order1886
from launcher import order1886_common as launcher

ROOT = Path(__file__).resolve().parents[1]


def values(**overrides):
    base = {'game_dir': 'game', 'display_mode': 'windowed', 'vsync': True, 'show_fps': False,
            'frame_rate': 30, 'aspect_ratio': 'original', 'mouse_look': True,
            'mouse_sensitivity': 100, 'mouse_invert_y': False, 'readbacks': 'relaxed',
            'performance_capture': False, 'fps_cap': 120}
    base.update(overrides)
    return base


def backend_settings(argv):
    """Parser output plus the mapping defaults the backend always supplies."""
    parsed = order1886.argument_parser().parse_args(argv)
    settings = vars(parsed)
    settings.update({'keyboard_bindings': {}, 'controller_bindings': {}})
    return settings


def environment(argv):
    return order1886.runtime_environment(ROOT / 'out' / 'runtime.exe', ROOT / 'out' / 'state',
                                        backend_settings(argv), {})


class CapReachesTheBackendTests(unittest.TestCase):
    def test_the_command_carries_the_cap(self):
        command = launcher.backend_command(values(fps_cap=90), 'play')
        self.assertIn('--fps-cap', command)
        self.assertEqual(command[command.index('--fps-cap') + 1], '90')

    def test_the_default_cap_is_carried_explicitly_rather_than_left_to_chance(self):
        command = launcher.backend_command(values(), 'play')
        self.assertIn('--fps-cap', command)
        self.assertEqual(command[command.index('--fps-cap') + 1], '120')

    def test_the_backend_parser_accepts_the_cap_and_refuses_the_range(self):
        parser = order1886.argument_parser()
        self.assertEqual(parser.parse_args(['--fps-cap', '240']).fps_cap, 240)
        for invalid in ('29', '241', 'ninety'):
            with self.subTest(invalid=invalid), self.assertRaises(SystemExit):
                parser.parse_args(['--fps-cap', invalid])

    def test_the_parsed_cap_reaches_the_runtime_environment(self):
        # 30 is lower than the engine rate, so it throttles; that is the only way a cap can
        # change the presented rate.
        env = environment(['--frame-rate', '60', '--fps-cap', '30'])
        self.assertEqual(env['ORDER1886_FPS_LIMIT'], '30')

    def test_a_cap_above_the_engine_rate_does_not_raise_the_rate(self):
        env = environment(['--frame-rate', '30', '--fps-cap', '120'])
        self.assertEqual(env['ORDER1886_FPS_LIMIT'], '30')

    def test_an_out_of_range_cap_is_refused_when_building_the_environment(self):
        settings = backend_settings([])
        settings['fps_cap'] = 500
        with self.assertRaises(ValueError):
            order1886.runtime_environment(ROOT / 'out' / 'runtime.exe', ROOT / 'out' / 'state',
                                          settings, {})


if __name__ == '__main__':
    unittest.main()
