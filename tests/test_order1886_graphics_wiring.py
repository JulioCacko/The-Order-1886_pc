"""Every graphics and runtime-path setting the launcher offers must reach the runtime."""
from pathlib import Path
import tempfile
import unittest

import order1886
from launcher import order1886_common as launcher
from launcher.order1886_options import FIELDS

ROOT = Path(__file__).resolve().parents[1]
CHOSEN = {'output_resolution': '3840x2160', 'sharpness': 40, 'anisotropy': 16, 'frames_queued': 2,
          'overlay_frametime': False, 'overlay_gpu': True, 'overlay_cpu': True, 'overlay_memory': True,
          'async_shaders': True, 'background_warmup': True, 'parallel_warmup': True,
          'speculative_readbacks': True}


def launcher_values(**overrides):
    base = {'game_dir': 'game', 'display_mode': 'windowed', 'vsync': True, 'show_fps': True,
            'frame_rate': 30, 'aspect_ratio': 'original', 'mouse_look': True,
            'mouse_sensitivity': 100, 'mouse_invert_y': False, 'readbacks': 'relaxed',
            'performance_capture': False, 'fps_cap': 120}
    base.update(overrides)
    return base


def through_backend(values):
    """Launcher values -> backend command line -> parsed backend settings."""
    command = launcher.backend_command(values, 'verify')
    settings = vars(order1886.argument_parser().parse_args(command[2:]))
    settings.update({'keyboard_bindings': {}, 'controller_bindings': {}})
    return settings


def runtime_ini(settings):
    with tempfile.TemporaryDirectory() as temporary:
        order1886.write_runtime_config(Path(temporary), settings)
        text = (Path(temporary) / 'runtime.ini').read_text(encoding='utf-8')
    return dict(line.split('=', 1) for line in text.splitlines() if '=' in line and not line.startswith('#'))


class GraphicsWiringTests(unittest.TestCase):
    def test_every_step_one_field_is_selectable(self):
        fields = {item['key']: item for item in FIELDS}
        for key in CHOSEN:
            with self.subTest(key=key):
                self.assertTrue(fields[key]['available'], fields[key]['reason'])
                for choice in fields[key].get('choices', []):
                    self.assertTrue(choice['available'], choice['label'])

    def test_chosen_values_reach_runtime_ini(self):
        values = runtime_ini(through_backend(launcher_values(**CHOSEN)))
        self.assertEqual(values['output_res'], '3840x2160')
        self.assertEqual((values['rcas'], values['rcas_strength']), ('1', '40'))
        self.assertEqual(values['anisotropy'], '16')
        self.assertEqual(values['frames_queued'], '2')
        self.assertEqual(values['async_shaders'], '1')
        self.assertEqual((values['overlay_frametime'], values['overlay_gpu'], values['overlay_cpu'],
                          values['overlay_ram'], values['overlay_vram']), ('0', '1', '1', '1', '1'))

    def test_chosen_values_reach_the_runtime_environment(self):
        env = order1886.runtime_environment(ROOT / 'out' / 'runtime.exe', ROOT / 'out' / 'state',
                                            through_backend(launcher_values(**CHOSEN)), {})
        for name in ('BACKGROUND_WARMUP', 'PARALLEL_WARMUP', 'DEFERRED_READBACK'):
            self.assertEqual(env['ORDER1886_' + name], '1', name)

    def test_defaults_keep_the_baseline(self):
        values = runtime_ini(through_backend(launcher_values()))
        self.assertEqual(values['output_res'], 'automatic')
        self.assertEqual((values['rcas'], values['anisotropy'], values['frames_queued'],
                          values['async_shaders']), ('0', '0', '1', '1'))
        env = order1886.runtime_environment(ROOT / 'out' / 'runtime.exe', ROOT / 'out' / 'state',
                                            through_backend(launcher_values()), {})
        for name in ('BACKGROUND_WARMUP', 'PARALLEL_WARMUP', 'DEFERRED_READBACK'):
            self.assertEqual(env['ORDER1886_' + name], '0', name)

    def test_invalid_values_are_refused(self):
        for key, bad in (('output_resolution', '800x600'), ('sharpness', 101), ('anisotropy', 3),
                         ('frames_queued', 4), ('async_shaders', 'yes')):
            with self.subTest(key=key), self.assertRaises(ValueError):
                order1886.graphics_settings({key: bad})


if __name__ == '__main__':
    unittest.main()
