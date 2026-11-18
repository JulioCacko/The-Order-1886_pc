"""The in-game menu (F1): the backend flag stays opt-in, the launcher setting is on by default."""
from pathlib import Path
import unittest

import order1886
from launcher import order1886_common as launcher
from launcher import order1886_options as options
from launcher import order1886_worker as worker

ROOT = Path(__file__).resolve().parents[1]


def environment(settings):
    return order1886.runtime_environment(ROOT / 'out' / 'runtime.exe', ROOT / 'out' / 'state', settings, {})


class InGameMenuTests(unittest.TestCase):
    def test_the_backend_leaves_the_menu_off_unless_asked_for(self):
        self.assertEqual(environment({})['ORDER1886_SETTINGS_MENU'], '0')
        self.assertEqual(environment({'in_game_menu': False})['ORDER1886_SETTINGS_MENU'], '0')

    def test_the_setting_reaches_the_runtime(self):
        self.assertEqual(environment({'in_game_menu': True})['ORDER1886_SETTINGS_MENU'], '1')

    def test_only_a_real_boolean_is_accepted(self):
        for invalid in ('1', 1, None, [True]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                environment({'in_game_menu': invalid})

    def test_the_catalog_exposes_the_option_on_by_default(self):
        field = next(item for item in options.FIELDS if item['key'] == 'game_menu')
        self.assertEqual(field['default'], True)
        self.assertEqual(field['kind'], 'boolean')
        self.assertEqual(field['page'], 'performance')
        self.assertTrue(field['available'])
        self.assertIn('F1', field['label'])
        self.assertNotIn('in_game_menu', [item['key'] for item in options.FIELDS])

    def test_the_launcher_passes_the_flag_unless_the_player_turned_it_off(self):
        base = {'game_dir': 'g', 'display_mode': 'windowed', 'vsync': True, 'show_fps': False}
        self.assertIn('--in-game-menu', launcher.backend_command(dict(base), 'play'))
        self.assertIn('--in-game-menu', launcher.backend_command(dict(base, game_menu=True), 'play'))
        self.assertNotIn('--in-game-menu', launcher.backend_command(dict(base, game_menu=False), 'play'))
        # The retired opt-in key must not keep an old "off" alive.
        self.assertIn('--in-game-menu', launcher.backend_command(dict(base, in_game_menu=False), 'play'))

    def test_the_setting_round_trips_through_the_worker(self):
        with worker_temp_state() as state:
            app = worker.Worker(state, ROOT)
            values = app.dispatch('settings.set', {'values': {'game_menu': True}})['settings']
            self.assertIs(values['game_menu'], True)
            values = app.dispatch('settings.set', {'values': {'game_menu': False}})['settings']
            self.assertIs(values['game_menu'], False)
            self.assertIs(launcher.load_launch_settings(state, {})['game_menu'], True)
            self.assertIs(launcher.load_launch_settings(state, {'game_menu': False})['game_menu'], False)


class worker_temp_state:
    def __enter__(self):
        import tempfile
        self._folder = tempfile.TemporaryDirectory()
        return Path(self._folder.name)

    def __exit__(self, *_exc):
        self._folder.cleanup()


if __name__ == '__main__':
    unittest.main()
