"""Direct play shares the GUI's settings and worker; shortcuts stay installation-local."""
import importlib.util
import os
import sys
from pathlib import Path
import tempfile
import tracemalloc
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('order_quick_launcher', ROOT / 'launcher/order1886_launcher.py')
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class QuickPlayTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows launcher entry point')
    def test_quick_entry_point_does_not_create_a_tk_window(self):
        for explicit in (False, True):
            with self.subTest(explicit=explicit), tempfile.TemporaryDirectory() as tmp:
                args = ['--state-dir', tmp] + (['--play'] if explicit else [])
                with patch.object(launcher, 'FROZEN', True), \
                     patch.object(sys, 'executable', str(Path(tmp) / 'Play The Order 1886.exe')), \
                     patch.object(launcher, 'run_saved_game', return_value=0) as run, \
                     patch('tkinter.Tk', side_effect=AssertionError('Direct play must not create a Tk window')):
                    self.assertEqual(launcher.main(args), 0)
                    run.assert_called_once()

    def test_long_sessions_do_not_keep_the_entire_log_in_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            launcher.save_settings(state / 'settings.json', dict(game_dir=str(state / 'Game')))
            def noisy(command, logfile, events, *args):
                for index in range(20000):
                    events.put(('line', str(index) + 'x' * 1000 + '\n'))
                events.put(('done', (0, 'play', False)))
            with patch('order1886.inspect_game'), patch('order1886.find_runtime', return_value=Path('runtime.exe')), \
                 patch.object(launcher, 'session_worker', side_effect=noisy):
                tracemalloc.start()
                try:
                    self.assertEqual(launcher.run_saved_game(state), 0)
                    _current, peak = tracemalloc.get_traced_memory()
                finally:
                    tracemalloc.stop()
            self.assertLess(peak, 2_000_000)

    def test_real_worker_exit_status_is_unpacked(self):
        for code in (0, 7, 130):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as tmp:
                state = Path(tmp)
                launcher.save_settings(state / 'settings.json', dict(game_dir=str(state / 'Game')))
                command = [sys.executable, '-c', f'print("quick fixture output"); raise SystemExit({code})']
                errors = []
                with patch('order1886.inspect_game'), patch('order1886.find_runtime', return_value=Path('runtime.exe')), \
                     patch.object(launcher, 'backend_command', return_value=command):
                    self.assertEqual(launcher.run_saved_game(state, on_error=errors.append), code)
                logs = list(state.glob('launcher-*.log'))
                self.assertEqual(len(logs), 1)
                self.assertIn('quick fixture output', logs[0].read_text(encoding='utf-8'))
                self.assertEqual(bool(errors), code == 7)

    def test_first_run_requests_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(launcher, 'session_worker') as worker:
                self.assertIsNone(launcher.run_saved_game(Path(tmp)))
                worker.assert_not_called()

    def test_saved_settings_use_the_same_worker_and_isolated_logs(self):
        with tempfile.TemporaryDirectory(prefix='Order quick ') as tmp:
            state = Path(tmp) / 'user state'
            values = dict(game_dir=str(Path(tmp) / 'Game files'), runtime='',
                display_mode='fullscreen', vsync=False, show_fps=True, frame_rate=60,
                aspect_ratio='original', presentation_filter='linear',
                mouse_look=False, mouse_sensitivity=175, mouse_invert_y=True)
            launcher.save_settings(state / 'settings.json', values)
            def worker(command, logfile, events, cancelled, stop_file, mode, cwd):
                self.assertEqual(command, launcher.backend_command(values, state=state, stop_file=stop_file))
                self.assertEqual(logfile.parent, state)
                self.assertEqual(stop_file.parent, state)
                self.assertEqual(mode, 'play')
                self.assertEqual(cwd, launcher.ROOT)
                events.put(('done', (0, 'play', False)))
            with patch('order1886.inspect_game'), patch('order1886.find_runtime', return_value=Path('runtime.exe')), \
                 patch('order1886.timing.validate_source') as timing, \
                 patch.object(launcher, 'session_worker', side_effect=worker) as called:
                self.assertEqual(launcher.run_saved_game(state), 0)
                called.assert_called_once()
            self.assertEqual(timing.call_args.args[:2], (Path(values['game_dir']) / 'eboot.bin', 60))

    def test_stale_runtime_opens_setup_without_spawning(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            launcher.save_settings(state / 'settings.json', dict(game_dir=str(state / 'Game')))
            with patch('order1886.inspect_game'), patch('order1886.find_runtime', side_effect=ValueError('Wrong runtime ABI')), \
                 patch.object(launcher, 'session_worker') as called:
                self.assertIsNone(launcher.run_saved_game(state))
                called.assert_not_called()

    def test_worker_failure_reports_the_log_and_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            launcher.save_settings(state / 'settings.json', dict(game_dir=str(state / 'Game')))
            errors = []
            def fail(command, logfile, events, *args):
                logfile.write_text('Runtime identity mismatch')
                events.put(('done', (2, 'play', False)))
            with patch('order1886.inspect_game'), patch('order1886.find_runtime', return_value=Path('runtime.exe')), \
                 patch.object(launcher, 'session_worker', side_effect=fail):
                self.assertEqual(launcher.run_saved_game(state, on_error=errors.append), 2)
            self.assertEqual(len(errors), 1)
            self.assertIn(str(state), errors[0])
            self.assertIn('2', errors[0])

    def test_unsupported_saved_setting_requests_setup_without_changing_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            launcher.save_settings(state / 'settings.json', dict(game_dir=str(state / 'Game'), frame_rate=90))
            errors = []
            with patch('order1886.inspect_game'), patch('order1886.find_runtime', return_value=Path('runtime.exe')), \
                 patch.object(launcher, 'session_worker') as called:
                self.assertIsNone(launcher.run_saved_game(state, on_error=errors.append))
                called.assert_not_called()
            self.assertIn('frame_rate', errors[0])
            self.assertEqual(launcher.read_settings(state / 'settings.json')['frame_rate'], 90)

    def test_relative_saved_paths_resolve_from_installation(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, install = Path(tmp) / 'state', Path(tmp) / 'Install folder'
            launcher.save_settings(state / 'settings.json', dict(game_dir='Game files', runtime='bin/custom.exe'))
            def complete(command, logfile, events, *args):
                events.put(('done', (0, 'play', False)))
            with patch.object(launcher, 'ROOT', install), patch('order1886.inspect_game') as inspect, \
                 patch('order1886.find_runtime', return_value=Path('runtime.exe')) as runtime, \
                 patch.object(launcher, 'session_worker', side_effect=complete):
                self.assertEqual(launcher.run_saved_game(state), 0)
            inspect.assert_called_once_with(install / 'Game files')
            runtime.assert_called_once_with(install / 'bin/custom.exe')
            self.assertEqual(launcher.read_settings(state / 'settings.json')['runtime'], 'bin/custom.exe')

    def test_corrupt_preferences_open_setup_without_overwriting_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / 'settings.json').write_text('{broken')
            with patch('order1886.inspect_game'), patch('order1886.find_runtime', return_value=Path('runtime.exe')), \
                 patch.object(launcher, 'session_worker') as called:
                self.assertIsNone(launcher.run_saved_game(state))
                called.assert_not_called()
            self.assertEqual((state / 'settings.json').read_text(), '{broken')

    def test_direct_play_preserves_unrecognized_preferences(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            saved = dict(game_dir=str(state / 'Game'), future_option='preserve me')
            launcher.save_settings(state / 'settings.json', saved)
            def complete(command, logfile, events, *args):
                events.put(('done', (0, 'play', False)))
            with patch('order1886.inspect_game'), patch('order1886.find_runtime', return_value=Path('runtime.exe')), \
                 patch.object(launcher, 'session_worker', side_effect=complete):
                self.assertEqual(launcher.run_saved_game(state), 0)
            self.assertEqual(launcher.read_settings(state / 'settings.json'), saved)

    @unittest.skipUnless(os.name == 'nt', 'Windows shortcuts')
    def test_shortcut_is_idempotent_and_handles_unicode_and_quotes(self):
        with tempfile.TemporaryDirectory(prefix="Order ' ç ") as tmp:
            install, desktop = Path(tmp) / 'Install folder', Path(tmp) / 'Desktop'
            install.mkdir()
            desktop.mkdir()
            target = install / 'Play The Order 1886.exe'
            target.write_bytes(b'fixture target - not executed')
            (install / 'The Order 1886.exe').write_bytes(b'fixture icon')
            with patch.dict(os.environ, {'PATH': str(Path(os.environ['SystemRoot']) / 'System32')}):
                first = launcher.create_desktop_shortcut(install, desktop)
                second = launcher.create_desktop_shortcut(install, desktop)
            self.assertEqual(first, second)
            self.assertTrue(first.is_file())
            self.assertEqual(len(list(desktop.glob('*.lnk'))), 1)


if __name__ == '__main__':
    unittest.main()
