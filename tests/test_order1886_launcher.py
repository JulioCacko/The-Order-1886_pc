"""Launcher regressions use a tiny host process, never the game or GPU."""
import importlib.util
from pathlib import Path
import queue
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


if __name__ == "__main__":
    unittest.main()
