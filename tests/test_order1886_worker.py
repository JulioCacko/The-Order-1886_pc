"""Worker protocol uses isolated state and fake sessions, never player saves."""
from pathlib import Path
import io
import json
import tempfile
import unittest
from unittest.mock import patch
from launcher import order1886_worker as worker
from tests.test_order1886_trophy_history import trophy_archive, PNG


class FrozenInstallationRootTests(unittest.TestCase):
    def test_both_package_layouts_resolve_to_the_package_folder(self):
        # Linux ships PyInstaller's one-directory worker one level deeper than Windows does, and
        # the backend found no runtime there before #114.
        package = Path('/opt/The Order 1886')
        self.assertEqual(worker.frozen_installation_root(package / 'bin/order1886-worker.exe'), package)
        self.assertEqual(worker.frozen_installation_root(package / 'bin/order1886-worker/order1886-worker'),
                         package)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "user"
        self.app = worker.Worker(self.state, worker.PROJECT_ROOT)

    def test_autosave_preserves_unknown_keys_and_false(self):
        self.state.mkdir()
        (self.state / "settings.json").write_text(json.dumps({"future": {"x": 1}, "vsync": True}))
        result = self.app.dispatch("settings.set", {"values": {"vsync": False}})
        saved = json.loads((self.state / "settings.json").read_text())
        self.assertFalse(saved["vsync"])
        self.assertEqual(saved["future"], {"x": 1})
        self.assertFalse(result["settings"]["vsync"])

    def test_update_preflight_checks_idle_lock_without_changing_settings(self):
        self.state.mkdir()
        settings = self.state / "settings.json"
        original = '{"future": 73, "mods_enabled": false}'
        settings.write_text(original, encoding="utf-8")
        self.assertEqual(self.app.dispatch("updates.preflight", {}), {"ready": True})
        self.assertEqual(settings.read_text(encoding="utf-8"), original)
        with worker.order1886.session_lock(self.state):
            pass

    def test_update_preflight_refuses_busy_or_external_session(self):
        self.app.busy = True
        with self.assertRaisesRegex(ValueError, "Stop the current session"):
            self.app.dispatch("updates.preflight", {})
        self.app.busy = False
        self.state.mkdir()
        with worker.order1886.session_lock(self.state):
            with self.assertRaisesRegex(RuntimeError, "already running"):
                self.app.dispatch("updates.preflight", {})

    def test_update_preflight_rejects_state_inside_original_game(self):
        with patch.object(self.app, "settings", return_value={"game_dir": str(self.root)}):
            with self.assertRaisesRegex(ValueError, "outside the selected game"):
                self.app.dispatch("updates.preflight", {})
        self.assertFalse((self.state / "session.lock").exists())

    def test_invalid_and_unavailable_values_do_not_write(self):
        for values in ({"frame_rate": 120}, {"mouse_sensitivity": True},
                       {"mouse_sensitivity": 501}, {"ui_language": "no"},
                       {"frame_generation": "dlss"}, {"command": "anything"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.app.dispatch("settings.set", {"values": values})
        self.assertFalse((self.state / "settings.json").exists())

    def test_catalog_includes_every_page_and_blocked_provider_choices(self):
        result = self.app.dispatch("state.get", {})
        self.assertEqual(len(result["pages"]), 7)
        fields = {field["key"]: field for field in result["fields"]}
        self.assertTrue(fields["vsync"]["available"])
        self.assertFalse(fields["frame_generation"]["available"])
        self.assertTrue(fields["frame_generation"]["reason"])
        self.assertEqual(len(result["languages"]), 13)

    def test_trophy_artwork_failure_does_not_hide_unlock_history(self):
        game = self.root / 'game'
        archive = game / 'sce_sys/trophy/trophy00.trp'
        archive.parent.mkdir(parents=True)
        archive.write_bytes(trophy_archive([('TROP001.PNG', PNG, 0)]))
        earned = [{'id': 1, 'unlocked_at': 1700000000}]
        with patch.object(self.app, 'settings', return_value={'game_dir': str(game)}), \
             patch.object(worker.order1886, 'inspect_game', return_value={'TITLE_ID': 'CUSA00076'}), \
             patch('scripts.order1886_trophy_history.read', return_value=earned):
            result = self.app.snapshot()
            self.assertEqual(result['trophy_catalog'][0]['id'], 1)
            self.assertTrue(result['trophy_catalog'][0]['icon'].startswith('data:image/png;base64,'))
            archive.write_bytes(b'corrupt')
            result = self.app.snapshot()
            self.assertEqual(result['trophies'], earned)
            self.assertEqual(result['trophy_catalog'], [])
            self.assertTrue(result['trophy_catalog_error'])

    def test_unrecognized_saved_values_are_not_silently_rewritten(self):
        self.state.mkdir()
        path = self.state / "settings.json"
        text = json.dumps({"frame_rate": 90, "future": 7})
        path.write_text(text)
        self.assertEqual(self.app.dispatch("state.get", {})["settings"]["frame_rate"], 90)
        self.assertEqual(path.read_text(), text)

    def test_custom_bindings_are_validated_before_autosave_and_restore(self):
        catalog = {'keyboard_sources': ['Q', 'Space'], 'controller_sources': ['a', 'b'],
                   'unbinding': True,
                   'keyboard_scancodes': {'Q': 20, 'Space': 44},
                   'buttons': [{'id': key, 'keyboard_default': [], 'controller_default': []}
                               for key in worker.order1886.inputs.BUTTONS]}
        with patch.object(worker.order1886, 'find_runtime', return_value=Path('fixture-runtime.exe')), \
             patch.object(worker.order1886, 'input_catalog', return_value=catalog):
            self.app.dispatch('settings.set', {'values': {'keyboard_bindings': {'cross': 'Q'}}})
            previous = (self.state / 'settings.json').read_bytes()
            with self.assertRaises(ValueError):
                self.app.dispatch('settings.set', {'values': {'keyboard_bindings': {'cross': 'NotAKey'}}})
            self.assertEqual((self.state / 'settings.json').read_bytes(), previous)
        with patch.object(worker.legacy, 'validate_launch_game', wraps=worker.legacy.validate_launch_game), \
             patch.object(worker.order1886, 'inspect_game', return_value={}), \
             patch.object(worker.order1886, 'find_runtime', return_value=Path('fixture-runtime.exe')), \
             patch.object(worker.order1886, 'input_catalog', side_effect=ValueError('input inventory failed')), \
             patch.object(worker.order1886.save_backup, 'restore') as restore:
            with self.assertRaisesRegex(ValueError, 'input inventory failed'):
                self.app.dispatch('session.start', {'backup': 'selected', 'confirmed': True})
            restore.assert_not_called()

    def test_invalid_keyboard_and_controller_maps_can_be_repaired_independently(self):
        self.state.mkdir()
        for first, second in (('keyboard_bindings', 'controller_bindings'),
                              ('controller_bindings', 'keyboard_bindings')):
            path = self.state / 'settings.json'
            path.write_text(json.dumps({first: {'cross': 'Unknown Input'}, second: 'malformed', 'future': 7}))
            self.app.dispatch('settings.set', {'values': {first: {}}})
            self.assertEqual(json.loads(path.read_text())[second], 'malformed')
            self.app.dispatch('settings.set', {'values': {second: {}}})
            self.assertEqual(json.loads(path.read_text())['future'], 7)

    def test_mutating_actions_require_confirmation(self):
        for method in ("saves.restore", "saves.import", "cache.clear"):
            with self.subTest(method=method), self.assertRaises(ValueError):
                self.app.dispatch(method, {})
        self.assertFalse(self.state.exists())

    def test_selected_save_cancel_or_failed_preflight_cannot_start(self):
        with self.assertRaises(ValueError):
            self.app.dispatch("session.start", {"backup": "old"})
        with patch.object(worker.legacy, "validate_launch_game", side_effect=ValueError("bad game")), \
             patch.object(worker.order1886.save_backup, "restore") as restore:
            with self.assertRaises(ValueError):
                self.app.dispatch("session.start", {"backup": "old", "confirmed": True})
            restore.assert_not_called()
        self.assertFalse(self.app.busy)

    def test_protocol_rejects_bad_requests_and_recovers(self):
        output = io.StringIO()
        source = io.StringIO('bad json\n{"version":2,"id":1,"method":"state.get"}\n'
                             '{"version":1,"id":2,"method":"__dict__"}\n'
                             '{"version":1,"id":3,"method":"state.get","params":{}}\n')
        worker.serve(self.app, source, output)
        replies = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(replies), 4)
        self.assertTrue(all("error" in item for item in replies[:3]))
        self.assertEqual(replies[-1]["id"], 3)
        self.assertIn("settings", replies[-1]["result"])

    def test_protocol_closes_worker_if_response_pipe_breaks(self):
        class BrokenOutput:
            def write(self, value):
                raise BrokenPipeError("parent exited")
            def flush(self):
                pass
        with patch.object(self.app, "close") as close:
            with self.assertRaises(BrokenPipeError):
                worker.serve(self.app, io.StringIO('{"version":1,"id":1,"method":"state.get"}\n'), BrokenOutput())
            close.assert_called_once()

    def test_ui_log_events_are_bounded(self):
        emitted = []
        self.app.emit = lambda kind, data: emitted.append((kind, data))
        self.app.put(("line", "x" * 100000))
        self.assertLess(len(emitted[0][1]), 2200)
        self.assertIn("session log", emitted[0][1])
        self.assertEqual(self.app.log_tail[-1], emitted[0][1])

    def test_protocol_size_bound(self):
        output = io.StringIO()
        worker.serve(self.app, io.StringIO("x" * (worker.MAX_REQUEST + 2) + "\n"), output)
        self.assertIn("error", json.loads(output.getvalue()))

    def test_bundled_worker_discovers_runtime_at_installation_root(self):
        installation = self.root / "portable"
        runtime = installation / "bin" / "order1886-runtime.exe"
        runtime.parent.mkdir(parents=True)
        runtime.touch()
        previous = worker.order1886.INSTALL_ROOT
        self.addCleanup(setattr, worker.order1886, "INSTALL_ROOT", previous)
        worker.Worker(self.state, installation)
        with patch("sys.frozen", True, create=True), patch.object(
                worker.order1886, "runtime_identity", return_value={
                    "build": {"game_profile": "order1886", "runtime_abi": "order1886-native-1"}}):
            self.assertEqual(worker.order1886.find_runtime(), runtime.resolve())


if __name__ == "__main__":
    unittest.main()

