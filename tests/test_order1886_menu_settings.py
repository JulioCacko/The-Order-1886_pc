"""A settings change made in the in-game menu survives to the launcher, and never the reverse."""
from pathlib import Path
import os
import tempfile
import unittest

import order1886
from launcher import order1886_worker as worker

ROOT = Path(__file__).resolve().parents[1]


def write_ini(state, **pairs):
    body = '# The Order: 1886 runtime settings\n' + ''.join(f'{k}={v}\n' for k, v in pairs.items())
    (state / 'runtime.ini').write_text(body, encoding='utf-8')


def age(state, name, seconds):
    stamp = (state / name).stat().st_mtime + seconds
    os.utime(state / name, (stamp, stamp))


class ImportTests(unittest.TestCase):
    def test_a_newer_runtime_ini_imports_the_menu_choices(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            (state / 'settings.json').write_text('{}', encoding='utf-8')
            write_ini(state, display_mode='fullscreen', vsync='0', show_fps='1',
                      presentation_filter='linear', mouse_look='0', mouse_invert_y='1',
                      mouse_sensitivity='250', fps_limit='60')
            age(state, 'runtime.ini', 5)
            changed = order1886.menu_settings_import(state, {'display_mode': 'borderless',
                                                             'vsync': True, 'frame_rate': 30})
            self.assertEqual(changed['display_mode'], 'fullscreen')
            self.assertIs(changed['vsync'], False)
            self.assertIs(changed['show_fps'], True)
            self.assertEqual(changed['presentation_filter'], 'linear')
            self.assertIs(changed['mouse_look'], False)
            self.assertIs(changed['mouse_invert_y'], True)
            self.assertEqual(changed['mouse_sensitivity'], 250)
            self.assertEqual(changed['frame_rate'], 60)

    def test_an_older_runtime_ini_never_overwrites_a_launcher_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            write_ini(state, display_mode='fullscreen', vsync='0')
            age(state, 'runtime.ini', -30)
            (state / 'settings.json').write_text('{"display_mode": "windowed"}', encoding='utf-8')
            self.assertEqual(order1886.menu_settings_import(state, {'display_mode': 'windowed'}), {})

    def test_unchanged_values_report_no_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            (state / 'settings.json').write_text('{}', encoding='utf-8')
            write_ini(state, display_mode='borderless', vsync='1')
            age(state, 'runtime.ini', 5)
            self.assertEqual(order1886.menu_settings_import(state, {'display_mode': 'borderless',
                                                                    'vsync': True}), {})

    def test_a_missing_or_corrupt_file_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            (state / 'settings.json').write_text('{}', encoding='utf-8')
            self.assertEqual(order1886.menu_settings_import(state, {}), {})
            (state / 'runtime.ini').write_text('garbage\n=\nvsync=maybe\nmouse_sensitivity=9999\n'
                                               'display_mode=sideways\nfps_limit=90\n', encoding='utf-8')
            age(state, 'runtime.ini', 5)
            self.assertEqual(order1886.menu_settings_import(state, {}), {})

    def test_unparsable_lines_do_not_hide_the_parsable_ones(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            (state / 'settings.json').write_text('{}', encoding='utf-8')
            (state / 'runtime.ini').write_text('vsync=notanumber\nshow_fps=1\n', encoding='utf-8')
            age(state, 'runtime.ini', 5)
            self.assertEqual(order1886.menu_settings_import(state, {'show_fps': False}),
                             {'show_fps': True})

    def test_an_engine_rate_the_launcher_does_not_offer_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            (state / 'settings.json').write_text('{}', encoding='utf-8')
            write_ini(state, fps_limit='90')
            age(state, 'runtime.ini', 5)
            self.assertEqual(order1886.menu_settings_import(state, {'frame_rate': 30}), {})


class WorkerPersistenceTests(unittest.TestCase):
    def test_the_worker_adopts_and_persists_a_menu_change_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            app = worker.Worker(state, ROOT)
            app.dispatch('settings.set', {'values': {'display_mode': 'borderless'}})
            write_ini(state, display_mode='fullscreen', vsync='1')
            age(state, 'runtime.ini', 5)
            values = app.snapshot()['settings']
            self.assertEqual(values['display_mode'], 'fullscreen')
            # Persisted, so the next read does not depend on the ini being newer again.
            self.assertEqual(app.settings()['display_mode'], 'fullscreen')
            age(state, 'runtime.ini', -30)
            self.assertEqual(app.snapshot()['settings']['display_mode'], 'fullscreen')


if __name__ == '__main__':
    unittest.main()
