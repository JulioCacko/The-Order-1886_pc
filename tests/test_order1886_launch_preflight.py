"""Reject incompatible launch patches before a worker starts, preserving preferences."""
import queue
import hashlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from tests.test_order1886_launcher import launcher
import order1886


class LaunchPreflightTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.game = self.base / 'Game'
        self.game.mkdir()
        (self.game / 'eboot.bin').write_bytes(b'unverified executable')
        self.state = self.base / 'State'
        self.values = launcher.load_launch_settings(self.state, {'game_dir': str(self.game)})
        self.metadata = {'TITLE_ID': 'CUSA00076', 'APP_VER': '01.02', 'VERSION': '01.00'}

    def app(self):
        app = SimpleNamespace(busy=False, commit_home=Mock(return_value=True), language='en',
                               state=self.state, values=self.values, root=Mock(),
                               log_text=None, draw=Mock(), show_logs=Mock(), events=queue.Queue())
        app.tr = launcher.Launcher.tr.__get__(app)
        return app

    def test_gui_rejects_unverified_timing_or_aspect_before_saving_or_starting(self):
        for rate, aspect in ((60, 'original'), (30, '16:9'), (60, '16:9')):
            with self.subTest(rate=rate, aspect=aspect):
                self.values.update(frame_rate=rate, aspect_ratio=aspect)
                app = self.app()
                with patch.object(order1886, 'inspect_game', return_value=self.metadata), \
                     patch.object(launcher, 'save_settings') as save, \
                     patch.object(launcher.threading, 'Thread') as worker, \
                     patch('tkinter.messagebox.showerror') as error:
                    launcher.Launcher.run(app, 'play')
                worker.assert_not_called()
                save.assert_not_called()
                self.assertFalse(app.busy)
                message = error.call_args.args[1]
                for text in ('01.02', '01.00', 'SHA256', '30 FPS', 'Original cinematic aspect'):
                    self.assertIn(text, message)

    def test_direct_play_rejection_opens_setup_and_preserves_saved_settings(self):
        self.values.update(frame_rate=60)
        launcher.save_settings(self.state / 'settings.json', self.values)
        before = (self.state / 'settings.json').read_bytes()
        errors = []
        with patch.object(order1886, 'inspect_game', return_value=self.metadata), \
             patch.object(order1886, 'find_runtime', return_value=Path('runtime.exe')), \
             patch.object(launcher, 'session_worker') as worker:
            self.assertIsNone(launcher.run_saved_game(self.state, on_error=errors.append))
        worker.assert_not_called()
        self.assertEqual((self.state / 'settings.json').read_bytes(), before)
        self.assertIn('01.02', errors[0])
        self.assertIn('Original cinematic aspect', errors[0])

    def test_unpatched_fullscreen_does_not_require_experimental_identity(self):
        self.values.update(frame_rate=30, aspect_ratio='original', display_mode='fullscreen')
        launcher.save_settings(self.state / 'settings.json', self.values)

        def finish(command, logfile, events, *args):
            events.put(('done', (0, 'play', False)))

        with patch.object(order1886, 'inspect_game', return_value=self.metadata), \
             patch.object(order1886, 'find_runtime', return_value=Path('runtime.exe')), \
             patch.object(launcher, 'session_worker', side_effect=finish) as worker:
            self.assertEqual(launcher.run_saved_game(self.state), 0)
        worker.assert_called_once()

    def test_matching_metadata_does_not_bypass_executable_hash(self):
        self.values.update(frame_rate=60)
        with patch.object(order1886, 'inspect_game', return_value=order1886.timing.EXPECTED_METADATA), \
             patch.object(launcher.threading, 'Thread') as worker, \
             patch('tkinter.messagebox.showerror') as error:
            launcher.Launcher.run(self.app(), 'play')
        worker.assert_not_called()
        self.assertIn('SHA256', error.call_args.args[1])

    def test_verified_timing_and_aspect_use_the_existing_guards_and_start(self):
        self.values.update(frame_rate=60, aspect_ratio='16:9')
        elf = b'verified test ELF'
        with patch.object(order1886, 'inspect_game', return_value=self.metadata), \
             patch.multiple(order1886.timing,
                            EXPECTED_SELF_SHA256=hashlib.sha256((self.game / 'eboot.bin').read_bytes()).hexdigest(),
                            EXPECTED_ELF_SHA256=hashlib.sha256(elf).hexdigest(),
                            EXPECTED_METADATA=self.metadata), \
             patch.object(order1886.timing.prepare, 'parse_self', return_value=(elf, None, None, None, None)), \
             patch.object(launcher.threading, 'Thread') as worker, \
             patch('tkinter.messagebox.showerror') as error:
            launcher.Launcher.run(self.app(), 'play')
        error.assert_not_called()
        worker.return_value.start.assert_called_once()

    def test_import_audit_remains_available_with_incompatible_selected_patches(self):
        self.values.update(frame_rate=60, aspect_ratio='16:9')
        with patch.object(order1886, 'inspect_game', return_value=self.metadata), \
             patch.object(launcher.threading, 'Thread') as worker, \
             patch('tkinter.messagebox.showerror') as error:
            launcher.Launcher.run(self.app(), 'verify')
        error.assert_not_called()
        worker.return_value.start.assert_called_once()


if __name__ == '__main__':
    unittest.main()
