"""Launcher regressions use a tiny host process, never the game or GPU."""
import importlib.util
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("order1886_launcher", ROOT / "launcher/order1886_launcher.py")
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def test_stale_runtime_error_does_not_blame_valid_game_files(self):
        app = launcher.Launcher.__new__(launcher.Launcher)
        app.values = {"game_dir": "valid-game", "runtime": "stale-runtime.exe"}
        backend = SimpleNamespace(inspect_game=Mock(return_value={}),
                                  find_runtime=Mock(side_effect=ValueError("Wrong runtime ABI")))
        with patch.dict(sys.modules, {"order1886": backend}):
            app.refresh_status()
        self.assertEqual(app.status, "Runtime needs attention")
        self.assertEqual(app.detail, "Wrong runtime ABI")
        backend.find_runtime.assert_called_once_with("stale-runtime.exe")

    def test_verify_uses_import_audit_without_conflicting_prepare_flag(self):
        values = dict(game_dir="C:/My Games/The Order", display_mode="borderless",
                      vsync=True, show_fps=False, runtime="")
        with patch.object(launcher, "FROZEN", True):
            command = launcher.backend_command(values, "verify", Path("state"), Path("state/stop"))
        self.assertEqual(command[:2], [sys.executable, "--run-backend"])
        self.assertIn("--check-imports", command)
        self.assertNotIn("--prepare-only", command)
        self.assertNotIn("--runtime", command)
        self.assertEqual(command[command.index("--stop-file") + 1], str(Path("state/stop")))
        self.assertEqual(command[command.index("--game-dir") + 1], values["game_dir"])
        self.assertEqual(command[command.index("--presentation-filter") + 1], 'fsr1')
        self.assertEqual(command[command.index('--frame-rate') + 1], '30')

    def test_settings_round_trip_and_corrupt_file_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "user/order1886/settings.json"
            values = {"game_dir": "C:/My Games/The Order", "vsync": False}
            launcher.save_settings(path, values)
            self.assertEqual(launcher.read_settings(path), values)
            self.assertFalse(path.with_suffix(".tmp").exists())
            path.write_text("broken json", encoding="utf-8")
            self.assertEqual(launcher.read_settings(path), {})

    def test_settings_refuse_state_inside_game_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            game = Path(directory) / "game"
            game.mkdir()
            path = game / "user/order1886/settings.json"
            with self.assertRaisesRegex(ValueError, "outside"):
                launcher.save_settings(path, {"game_dir": str(game)})
            self.assertEqual(list(game.iterdir()), [])

    @unittest.skipUnless(os.name == 'nt', 'Hidden Windows Tk settings check')
    def test_overlay_default_and_explicit_saved_false(self):
        import tkinter as tk
        cases = (({}, True, 'fsr1', 'Linear', 'linear', 30, '60 FPS (experimental)', 60),
                 ({'show_fps': False, 'presentation_filter': 'linear', 'frame_rate': 60}, False,
                  'linear', 'FSR 1 (spatial)', 'fsr1', 60, '30 FPS (baseline)', 30))
        for saved, expected, filter_expected, choose_label, saved_filter, initial_rate, rate_label, final_rate in cases:
            with self.subTest(saved=saved), tempfile.TemporaryDirectory() as directory:
                state = Path(directory)
                launcher.save_settings(state / 'settings.json',
                                       {'game_dir': str(state / 'missing-game'), **saved})
                root = tk.Tk()
                root.withdraw()
                try:
                    app = launcher.Launcher(root, state)
                    self.assertIs(app.values['show_fps'], expected)
                    self.assertEqual(app.values['presentation_filter'], filter_expected)
                    self.assertEqual(app.values['frame_rate'], initial_rate)
                    self.assertEqual(app.values['aspect_ratio'], '16:9')
                    app.settings()
                    pending, labels, widgets = [app.settings_frame], [], []
                    while pending:
                        widget = pending.pop()
                        widgets.append(widget)
                        pending.extend(widget.winfo_children())
                        if widget.winfo_class() == 'Checkbutton':
                            labels.append(widget.cget('text'))
                    self.assertIn('Performance overlay (F9)', labels)
                    self.assertTrue(any(w.winfo_class() == 'Label' and 'Chapters 6 and 9' in w.cget('text')
                                        for w in widgets))
                    next(w for w in widgets if w.winfo_class() == 'Radiobutton'
                         and w.cget('text') == choose_label).invoke()
                    next(w for w in widgets if w.winfo_class() == 'Radiobutton'
                         and w.cget('text') == rate_label).invoke()
                    next(w for w in widgets if w.winfo_class() == 'Radiobutton'
                         and w.cget('text') == 'Original cinematic aspect').invoke()
                    next(w for w in widgets if w.winfo_class() == 'Button'
                         and w.cget('text') == 'Save settings').invoke()
                    persisted = launcher.read_settings(state / 'settings.json')
                    self.assertEqual(persisted['presentation_filter'], saved_filter)
                    self.assertIs(persisted['show_fps'], expected)
                    self.assertEqual(persisted['frame_rate'], final_rate)
                    self.assertEqual(persisted['aspect_ratio'], 'original')
                    command = launcher.backend_command(persisted, state=state)
                    self.assertEqual(command[command.index('--presentation-filter') + 1], saved_filter)
                    self.assertEqual(command[command.index('--frame-rate') + 1], str(final_rate))
                    self.assertEqual(command[command.index('--aspect-ratio') + 1], 'original')
                finally:
                    root.destroy()

    def test_stop_before_start_does_not_spawn_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            events, cancelled = queue.Queue(), threading.Event()
            cancelled.set()
            with patch.object(launcher.subprocess, "Popen") as popen:
                launcher.session_worker(["unused"], base / "session.log", events,
                                        cancelled, base / "stop", "play", base)
            popen.assert_not_called()
            self.assertIn("stopped before backend startup", (base / "session.log").read_text())
            self.assertIn(("done", (130, "play", True)), list(events.queue))

    @unittest.skipUnless(os.name == 'nt', 'Native Windows launch controls')
    def test_quick_controls_persist_and_preserve_advanced_settings(self):
        import tkinter as tk
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            launcher.save_settings(state / 'settings.json', {
                'game_dir': str(state / 'missing-game'), 'runtime': 'custom-runtime.exe',
                'vsync': False, 'show_fps': False})
            root = tk.Tk()
            root.withdraw()
            try:
                app = launcher.Launcher(root, state)
                app.home_fields['display_mode'].set('Windowed')
                app.home_fields['presentation_filter'].set('Linear')
                app.home_fields['frame_rate'].set('60 FPS (experimental)')
                self.assertTrue(app.commit_home())
                saved = launcher.read_settings(state / 'settings.json')
                self.assertEqual(saved['display_mode'], 'windowed')
                self.assertEqual(saved['presentation_filter'], 'linear')
                self.assertEqual(saved['frame_rate'], 60)
                self.assertEqual(saved['runtime'], 'custom-runtime.exe')
                self.assertIs(saved['vsync'], False)
                self.assertIs(saved['show_fps'], False)
                self.assertIn('Chapters 6 and 9', app.warning.cget('text'))
                with patch.object(app, 'play_or_stop') as play:
                    app.activate(SimpleNamespace(widget=app.game_entry))
                    app.activate(SimpleNamespace(widget=app.quick_controls[0]))
                    play.assert_not_called()
                    app.activate(SimpleNamespace(widget=root))
                    play.assert_called_once()
                before = (state / 'settings.json').read_bytes()
                app.home_fields['game_dir'].set(str(state))
                with patch('tkinter.messagebox.showerror') as error:
                    self.assertFalse(app.commit_home())
                    error.assert_called_once()
                self.assertEqual((state / 'settings.json').read_bytes(), before)
                self.assertEqual(app.home_fields['game_dir'].get(), saved['game_dir'])
            finally:
                root.destroy()

    def test_spawn_failure_is_saved_and_returns_to_idle(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            events = queue.Queue()
            launcher.session_worker([str(base / "missing.exe")], base / "session.log", events,
                                    threading.Event(), base / "stop", "play", base)
            self.assertIn("Could not start session", (base / "session.log").read_text())
            self.assertIn(("done", (1, "play", False)), list(events.queue))

    def test_live_output_stop_and_repeated_session(self):
        with tempfile.TemporaryDirectory(prefix="Order launcher spaces ") as directory:
            base = Path(directory)
            token = base / "stop"
            script = ("import pathlib,sys,time; token=pathlib.Path(sys.argv[1]); "
                      "print('backend ready', flush=True); "
                      "\nwhile not token.exists(): time.sleep(.01)\n"
                      "print('backend stopped', flush=True)")
            for iteration in range(2):
                events, cancelled = queue.Queue(), threading.Event()
                command = [sys.executable, "-u", "-c", script, str(token)]
                thread = threading.Thread(target=launcher.session_worker,
                    args=(command, base / f"session-{iteration}.log", events,
                          cancelled, token, "play", base))
                thread.start()
                deadline = time.monotonic() + 10
                messages = []
                while time.monotonic() < deadline:
                    item = events.get(timeout=10)
                    messages.append(item)
                    if item == ("line", "backend ready\n"):
                        break
                else:
                    self.fail("Host backend did not become ready")
                cancelled.set()
                token.touch()
                thread.join(10)
                self.assertFalse(thread.is_alive(), "Stopped backend must be reaped")
                messages.extend(list(events.queue))
                self.assertIn(("done", (0, "play", True)), messages)
                self.assertIn(("line", "backend stopped\n"), messages)
                self.assertFalse(token.exists())
                self.assertIn("Launcher command:", (base / f"session-{iteration}.log").read_text())


    def test_session_file_is_backend_output_and_reaches_ui_with_native_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            events = queue.Queue()
            outputs = []
            popen = subprocess.Popen

            def capture(*args, **kwargs):
                outputs.append(kwargs['stdout'])
                return popen(*args, **kwargs)

            command = [sys.executable, '-c', "print('STOP: native compatibility failure'); raise SystemExit(23)"]
            with patch.object(launcher.subprocess, 'Popen', side_effect=capture):
                launcher.session_worker(command, base / 'session.log', events,
                                        threading.Event(), base / 'stop', 'play', base)
            self.assertNotEqual(outputs, [subprocess.PIPE])
            self.assertTrue(hasattr(outputs[0], 'fileno'))
            self.assertIn(('line', 'STOP: native compatibility failure\n'), list(events.queue))
            self.assertIn(('done', (23, 'play', False)), list(events.queue))
            self.assertIn('Backend exit code: 23', (base / 'session.log').read_text())

    @unittest.skipUnless(os.name == 'nt', 'Windows recovered HANDLE ownership')
    def test_recovered_stdout_stderr_do_not_own_borrowed_or_shared_handle(self):
        with tempfile.TemporaryDirectory() as directory:
            script = r'''
import ctypes, importlib.util, msvcrt, os, pathlib, sys
root, output = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
spec = importlib.util.spec_from_file_location('launcher_handle_test', root / 'launcher/order1886_launcher.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.GetStdHandle.argtypes = [ctypes.c_ulong]
kernel.GetStdHandle.restype = ctypes.c_void_p
kernel.SetStdHandle.argtypes = [ctypes.c_ulong, ctypes.c_void_p]
saved_handles = [kernel.GetStdHandle(code & 0xffffffff) for code in (-11, -12)]
saved_streams = sys.stdout, sys.stderr
with output.open('wb', buffering=0) as borrowed:
    handle = msvcrt.get_osfhandle(borrowed.fileno())
    for code in (-11, -12):
        assert kernel.SetStdHandle(code & 0xffffffff, handle)
    try:
        sys.stdout = sys.stderr = None
        launcher.attach_stdio()
        first, second = sys.stdout, sys.stderr
        print('first stream', flush=True)
        first.close()
        print('second stream', file=second, flush=True)
        second.close()
        borrowed.write(b'borrowed handle still open\n')
    finally:
        sys.stdout, sys.stderr = saved_streams
        for code, saved in zip((-11, -12), saved_handles):
            kernel.SetStdHandle(code & 0xffffffff, saved)
'''
            output = Path(directory) / 'recovered.log'
            result = subprocess.run([sys.executable, '-c', script, str(ROOT), str(output)],
                                    capture_output=True, text=True, timeout=15,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('borrowed handle still open', output.read_text())


if __name__ == "__main__":
    unittest.main()
