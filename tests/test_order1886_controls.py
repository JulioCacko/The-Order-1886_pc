"""Mouse settings cross the desktop/backend boundary and survive restart."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import order1886

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('order_controls_launcher', ROOT / 'launcher/order1886_launcher.py')
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class ControlSettingsTests(unittest.TestCase):
    def test_mouse_settings_reach_backend(self):
        values = dict(game_dir='game', display_mode='windowed', vsync=True, show_fps=False,
                      mouse_look=False, mouse_sensitivity=175, mouse_invert_y=True)
        command = launcher.backend_command(values)
        for key, expected in (('--mouse-look', '0'), ('--mouse-sensitivity', '175'), ('--mouse-invert-y', '1')):
            self.assertIn(key, command)
            self.assertEqual(command[command.index(key) + 1], expected)

    def test_mouse_settings_written_to_runtime_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            user = Path(tmp)
            order1886.write_runtime_config(user, dict(mouse_look=False, mouse_sensitivity=175, mouse_invert_y=True))
            content = (user / 'runtime.ini').read_text()
            for line in ('mouse_look=0\n', 'mouse_sensitivity=175\n', 'mouse_invert_y=1\n'):
                self.assertIn(line, content)
            for invalid in (0, 501, -1, 1.5, True, 'fast'):
                with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'sensitivity'):
                    order1886.write_runtime_config(user, dict(mouse_sensitivity=invalid))

    @unittest.skipUnless(__import__('os').name == 'nt', 'Windows Tk desktop')
    def test_mouse_preferences_persist(self):
        import tkinter as tk
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'state'
            launcher.save_settings(state / 'settings.json', dict(game_dir=str(Path(tmp) / 'game'),
                mouse_look=False, mouse_sensitivity=175, mouse_invert_y=True))
            root = tk.Tk()
            try:
                app = launcher.DesktopLauncher(root, state)
                self.assertIs(app.values['mouse_look'], False)
                self.assertEqual(app.values['mouse_sensitivity'], 175)
                self.assertIs(app.values['mouse_invert_y'], True)
                self.assertIn('mouse_look', app.page_fields)
                app.page_fields['mouse_look'].set(True)
                app.page_fields['mouse_sensitivity'].set(225)
                app.page_fields['mouse_invert_y'].set(False)
                with patch.object(app, 'refresh_status'):
                    self.assertTrue(app.save_page_settings())
                saved = launcher.read_settings(state / 'settings.json')
                self.assertIs(saved['mouse_look'], True)
                self.assertEqual(saved['mouse_sensitivity'], 225)
                self.assertIs(saved['mouse_invert_y'], False)
            finally:
                root.destroy()


if __name__ == '__main__':
    unittest.main()
