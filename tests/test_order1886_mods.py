"""Asset overlays use tiny fixtures; never mount or mutate the actual game."""
import json
import os
from pathlib import Path
import stat
import tempfile
import sys
import unittest
from unittest.mock import patch

import order1886
import order1886_mods as mods


class ModOverlayTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.game, self.state, self.mods = [self.base / name for name in ('game', 'state', 'mods')]
        for path in (self.game, self.state, self.mods):
            path.mkdir()
        self.put(self.game / '_data/chapter/asset', b'original')
        self.put(self.game / '_data/other', b'untouched')
        self.put(self.game / 'eboot.bin', b'original executable')
        self.put(self.game / 'archivemap.bin', b'original index')
        self.put(self.mods / 'First/_data/chapter/asset', b'first')
        self.put(self.mods / 'Second/_data/chapter/asset', b'second')

    @staticmethod
    def put(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def build(self, enabled=True, order=('First',)):
        with order1886.session_lock(self.state):
            return mods.build_overlay(self.game, self.state, self.mods, enabled, list(order))

    def test_default_disabled_new_folders_and_off_restore_original_mount(self):
        self.assertEqual(mods.discover(self.mods), ['First', 'Second'])
        self.assertEqual(self.build(False), self.game)
        self.assertEqual(self.build(True, []), self.game)
        self.assertFalse((self.state / 'mod-overlays').exists())
        overlay = self.build()
        self.assertEqual((overlay / '_data/chapter/asset').read_bytes(), b'first')
        self.assertEqual(self.build(False), self.game)
        self.assertFalse(overlay.exists())
        self.assertEqual((self.game / '_data/chapter/asset').read_bytes(), b'original')

    def test_order_conflicts_replacements_and_originals_are_immutable(self):
        replacements, conflicts = mods.plan(self.game, self.mods, True, ['First', 'Second'])
        self.assertEqual(conflicts, [('_data/chapter/asset', 'First', 'Second')])
        self.assertEqual(len(replacements), 2)
        overlay = self.build(order=['First', 'Second'])
        self.assertEqual((overlay / '_data/chapter/asset').read_bytes(), b'second')
        self.assertEqual((overlay / '_data/other').read_bytes(), b'untouched')
        self.assertFalse(os.path.samefile(overlay / '_data/chapter/asset', self.mods / 'Second/_data/chapter/asset'))
        second = self.build(order=['Second', 'First'])
        self.assertEqual((second / '_data/chapter/asset').read_bytes(), b'first')
        self.assertFalse(overlay.exists())
        self.assertEqual((self.mods / 'Second/_data/chapter/asset').read_bytes(), b'second')

    def test_selected_game_inside_managed_storage_is_never_cleaned(self):
        active = self.build()
        before = {str(p.relative_to(active)): p.read_bytes() for p in active.rglob('*') if p.is_file()}
        for game in (active, active / '_data', self.state / 'mod-overlays'):
            for enabled in (False, True):
                with self.subTest(game=game, enabled=enabled), self.assertRaises(ValueError):
                    mods.build_overlay(game, self.state, self.mods, enabled, ['First'])
                self.assertEqual({str(p.relative_to(active)): p.read_bytes()
                                  for p in active.rglob('*') if p.is_file()}, before)

    def test_readonly_source_attributes_never_change(self):
        original = self.game / '_data/other'
        original.chmod(stat.S_IREAD)
        self.addCleanup(original.chmod, stat.S_IREAD | stat.S_IWRITE)
        before = original.stat().st_mode
        overlay = self.build()
        self.assertFalse(os.path.samefile(overlay / '_data/other', original))
        self.build(False)
        self.assertEqual(original.stat().st_mode, before)
        self.assertEqual(original.read_bytes(), b'untouched')

    def test_failed_build_preserves_active_overlay_and_crash_staging_is_recovered(self):
        active = self.build()
        pointer = (self.state / 'mod-overlays/active.json').read_bytes()
        with patch.object(mods, 'make_link', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.build(order=['Second'])
        self.assertEqual((self.state / 'mod-overlays/active.json').read_bytes(), pointer)
        self.assertTrue(active.exists())
        crash = self.state / 'mod-overlays' / ('overlay-' + 'a' * 32)
        crash.mkdir()
        (crash / 'partial').write_bytes(b'partial')
        self.build(order=['Second'])
        self.assertFalse(crash.exists())

    def test_config_validation_and_path_escape(self):
        for value in (None, {}, 'First', ['../First'], ['First/child'], ['First', 'first'], ['First', 'First'], [3], ['CON'], ['First.']):
            with self.subTest(value=value), self.assertRaises(ValueError):
                mods.plan(self.game, self.mods, True, value)
        for enabled in (1, 'yes', None):
            with self.assertRaises(ValueError):
                mods.plan(self.game, self.mods, enabled, [])
        with self.assertRaises(ValueError):
            self.build(order=['Missing'])

    def test_reject_system_executable_and_file_directory_collisions(self):
        for name in ('eboot.bin', 'sce_module/runtime.prx', 'sce_sys/param.sfo', 'bin/helper.exe', 'sce_discmap.plt', '_data/script.exe'):
            path = self.mods / 'Bad' / name
            self.put(path, b'bad')
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.build(order=['Bad'])
            path.unlink()
        self.put(self.mods / 'Collision/_data/chapter/asset/child', b'bad')
        with self.assertRaises(ValueError):
            self.build(order=['Collision'])

    def test_asset_index_is_supported_but_empty_mod_is_rejected(self):
        self.put(self.mods / 'Index/archivemap.bin', b'mod index')
        overlay = self.build(order=['Index'])
        self.assertEqual((overlay / 'archivemap.bin').read_bytes(), b'mod index')
        self.assertEqual((self.game / 'archivemap.bin').read_bytes(), b'original index')
        (self.mods / 'Empty').mkdir()
        with self.assertRaises(ValueError):
            self.build(order=['Empty'])

    def test_redirected_mod_and_overlay_paths_are_rejected(self):
        target = self.base / 'outside'
        target.mkdir()
        (target / 'keep').write_text('keep')
        junction = self.mods / 'Redirected'
        if os.name == 'nt':
            import _winapi
            _winapi.CreateJunction(str(target), str(junction))
            self.addCleanup(os.rmdir, junction)
        else:
            junction.symlink_to(target, target_is_directory=True)
            self.addCleanup(junction.unlink)
        with self.assertRaises(ValueError):
            self.build(order=['Redirected'])
        with self.assertRaises(ValueError):
            mods.discover(self.mods)
        self.assertEqual((target / 'keep').read_text(), 'keep')

    def test_session_lock_blocks_backend_before_overlay_mutation(self):
        with order1886.session_lock(self.state), patch.object(mods, 'build_overlay') as build:
            self.assertEqual(order1886.main(['--game-dir', str(self.game), '--state-dir', str(self.state),
                                           '--mods-dir', str(self.mods), '--mods-enabled', '1',
                                           '--mods-order', '["First"]']), 2)
        build.assert_not_called()

    def test_mod_sources_cannot_be_used_for_state_and_link_fallback_copies(self):
        state = self.mods / 'First/state'
        self.assertEqual(order1886.main(['--game-dir', str(self.game), '--state-dir', str(state),
                                        '--mods-dir', str(self.mods), '--prepare-only']), 2)
        self.assertFalse(state.exists())
        with patch.object(mods.os, 'link', side_effect=OSError('different volume')):
            overlay = self.build()
        self.assertEqual((overlay / '_data/other').read_bytes(), b'untouched')
        self.assertFalse(os.path.samefile(overlay / '_data/other', self.game / '_data/other'))

    def test_backend_prepares_original_and_mounts_overlay_only_for_runtime(self):
        metadata = {'TITLE': 'The Order', 'TITLE_ID': 'CUSA00076', 'APP_VER': '01.00'}
        runtime = self.base / 'runtime.exe'
        runtime.write_bytes(b'fixture')
        calls = []
        def finish(command, env, log, *args):
            mount = Path(command[command.index('--app0') + 1])
            self.assertNotEqual(mount, self.game)
            self.assertEqual((mount / '_data/chapter/asset').read_bytes(), b'first')
            with self.assertRaises(RuntimeError):
                with order1886.session_lock(self.state):
                    self.fail('Runtime must retain the session lock')
            calls.append(mount)
            Path(log).write_text('fixture exit')
            return {'exit_code': 0, 'timed_out': False}
        args = ['--game-dir', str(self.game), '--state-dir', str(self.state), '--mods-dir', str(self.mods),
                '--mods-enabled', '1', '--mods-order', '["First"]']
        with patch.object(order1886, 'inspect_game', return_value=metadata), \
             patch.object(order1886, 'find_runtime', return_value=runtime), \
             patch.object(order1886, 'prepare_game', return_value={'image_sha256': 'fixture'}) as prepare, \
             patch.object(order1886.save_backup, 'backup'), \
             patch.object(order1886, 'run_process', side_effect=finish):
            self.assertEqual(order1886.main(args), 0)
        prepare.assert_called_once_with(self.game, self.state / 'prepared', frame_rate=30, aspect_ratio='original')
        report = json.loads((self.state / 'logs/last-run.json').read_text())
        self.assertEqual(report['game'], str(self.game))
        self.assertEqual(report['mounted_game'], str(calls[0]))
        before = (self.state / 'mod-overlays/active.json').read_bytes()
        with patch.object(order1886, 'inspect_game', return_value=metadata), \
             patch.object(order1886, 'find_runtime', return_value=runtime), \
             patch.object(order1886, 'prepare_game', side_effect=ValueError('Unverified original hash')), \
             patch.object(order1886, 'run_process') as run:
            self.assertEqual(order1886.main(args + ['--frame-rate', '60']), 2)
        run.assert_not_called()
        self.assertEqual((self.state / 'mod-overlays/active.json').read_bytes(), before)

    def test_links_in_mod_assets_and_owned_cleanup_are_not_followed(self):
        target = self.base / 'outside'
        target.mkdir()
        (target / 'keep').write_bytes(b'keep')
        active = self.build()
        junction = active / 'redirected'
        if os.name == 'nt':
            import _winapi
            _winapi.CreateJunction(str(target), str(junction))
            self.addCleanup(os.rmdir, junction)
        else:
            junction.symlink_to(target, target_is_directory=True)
            self.addCleanup(junction.unlink)
        with self.assertRaises(ValueError):
            self.build(False)
        pointer = (self.state / 'mod-overlays/active.json').read_bytes()
        with self.assertRaises(ValueError):
            self.build(order=['Second'])
        self.assertEqual((self.state / 'mod-overlays/active.json').read_bytes(), pointer)
        self.assertEqual((target / 'keep').read_bytes(), b'keep')
        source_link = self.mods / 'First/_data/chapter/linked'
        try:
            source_link.symlink_to(target / 'keep')
        except OSError:
            # Windows without symlink privilege still exercises actual reparse points above.
            info = (target / 'keep').stat()
            from types import SimpleNamespace
            reparse = SimpleNamespace(st_mode=info.st_mode, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
            with patch.object(Path, 'lstat', return_value=reparse), self.assertRaises(ValueError):
                mods._stat(source_link)
        else:
            self.addCleanup(source_link.unlink)
            with self.assertRaises(ValueError):
                mods.plan(self.game, self.mods, True, ['First'])

    def test_case_ambiguity_is_rejected_and_same_volume_uses_donor_hardlinks(self):
        from types import SimpleNamespace
        with patch.object(Path, 'iterdir', return_value=iter([Path('A'), Path('a')])), \
             patch.object(mods, '_stat', return_value=SimpleNamespace(st_mode=stat.S_IFREG | stat.S_IWRITE)):
            with self.assertRaisesRegex(ValueError, 'Ambiguous'):
                mods._entries(self.mods)
        overlay = self.build()
        self.assertTrue(os.path.samefile(overlay / '_data/other', self.game / '_data/other'))


class LauncherModTests(unittest.TestCase):
    def test_relative_mod_root_uses_installation_in_every_working_directory(self):
        from launcher import order1886_launcher as launcher
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            installation, other = base / 'installation', base / 'other'
            for root, content in ((installation, b'expected'), (other, b'wrong')):
                folder = root / 'mods/First/_data'
                folder.mkdir(parents=True)
                (folder / 'asset').write_bytes(content)
            previous = Path.cwd()
            try:
                os.chdir(other)
                with patch.object(launcher, 'ROOT', installation), patch.object(order1886, 'ROOT', installation):
                    values = launcher.load_launch_settings(base / 'state', {'game_dir': str(base / 'game')})
                    values.update(mods_dir='mods', mods_enabled=True, mod_order=['First'])
                    command = launcher.backend_command(values)
                    selected = Path(command[command.index('--mods-dir') + 1])
                    self.assertEqual(selected, installation / 'mods')
                    self.assertEqual((selected / 'First/_data/asset').read_bytes(), b'expected')
            finally:
                os.chdir(previous)

    @unittest.skipUnless(os.name == 'nt', 'Native Tk malformed mod settings')
    def test_malformed_saved_mod_settings_are_visible_and_not_rewritten_on_open(self):
        import tkinter as tk
        from launcher import order1886_launcher as launcher
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            values = {'game_dir': str(state / 'missing'), 'mods_dir': 123, 'mods_enabled': 'yes', 'mod_order': []}
            launcher.save_settings(state / 'settings.json', values)
            before = (state / 'settings.json').read_bytes()
            window = tk.Tk()
            window.withdraw()
            try:
                app = launcher.DesktopLauncher(window, state)
                self.assertIn('Saved mod settings are invalid', app.mod_notice.cget('text'))
                self.assertFalse(app.page_fields['mods_enabled'].get())
                self.assertEqual((state / 'settings.json').read_bytes(), before)
                with self.assertRaises(ValueError):
                    launcher.backend_command(app.values)
            finally:
                window.destroy()

    def test_saved_direct_play_keeps_explicit_order_and_disabled_default(self):
        from launcher import order1886_launcher as launcher
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            root = state / 'mods'
            for name in ('First', 'Second', 'New'):
                (root / name / '_data').mkdir(parents=True)
                (root / name / '_data/asset').write_bytes(name.encode())
            values = launcher.load_launch_settings(state, {'game_dir': str(state / 'game')})
            self.assertEqual(values['mod_order'], [])
            self.assertIs(values['mods_enabled'], False)
            values.update(mods_dir=str(root), mods_enabled=True, mod_order=['Second', 'First'])
            launcher.save_settings(state / 'settings.json', values)
            reloaded = launcher.load_launch_settings(state)
            command = launcher.backend_command(reloaded)
            self.assertEqual(json.loads(command[command.index('--mods-order') + 1]), ['Second', 'First'])
            self.assertNotIn('New', command[command.index('--mods-order') + 1])
            self.assertNotIn('--mods-enabled', launcher.backend_command(reloaded, 'verify'))

    @unittest.skipUnless(os.name == 'nt', 'Native Tk mod selection')
    def test_launcher_mod_selection_order_and_changed_folder_require_explicit_enable(self):
        import tkinter as tk
        from launcher import order1886_launcher as launcher
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            root = state / 'mods'
            for name in ('First', 'Second'):
                (root / name / '_data').mkdir(parents=True)
                (root / name / '_data/asset').write_bytes(name.encode())
            launcher.save_settings(state / 'settings.json', {'game_dir': str(state / 'missing-game'), 'mods_dir': str(root)})
            window = tk.Tk()
            window.withdraw()
            try:
                app = launcher.DesktopLauncher(window, state)
                self.assertEqual(app.mod_order, [])
                for name in ('First', 'Second'):
                    app.mod_list.selection_clear(0, 'end')
                    app.mod_list.selection_set(app.mod_names.index(name))
                    app.toggle_mod()
                app.move_mod(-1)
                self.assertEqual(app.mod_order, ['Second', 'First'])
                self.assertTrue(app.save_page_settings())
                self.assertEqual(launcher.read_settings(state / 'settings.json')['mod_order'], ['Second', 'First'])
                app.page_fields['mods_dir'].set(str(state / 'different-mods-folder'))
                app.refresh_mods()
                self.assertEqual(app.mod_order, [])
                self.assertIn('attention', app.mod_notice.cget('text'))
            finally:
                window.destroy()

    def test_packaging_declares_mod_helper_in_data_sources_and_frozen_imports(self):
        root = Path(__file__).resolve().parents[1]
        build = (root / 'packaging/windows/order1886-build.ps1').read_text(encoding='utf-8')
        smoke = (root / 'packaging/windows/order1886-smoke.py').read_text(encoding='utf-8')
        self.assertEqual(build.count("'order1886_mods.py'"), 2)
        self.assertIn('--hidden-import order1886_mods', build)
        self.assertIn('"order1886_mods.py"', smoke)


if __name__ == '__main__':
    unittest.main()
