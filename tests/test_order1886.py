"""Order-specific safety and lifecycle tests; these do not claim game compatibility."""
from paths import ROOT
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import order1886


class OrderBackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.game = self.base / 'The Order game files'
        self.user = self.base / 'isolated state'
        self.user.mkdir()
        for name in order1886.REQUIRED_FILES:
            target = self.game / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'fixture-' + name.encode())
        (self.game / '_data').mkdir()
        (self.game / 'archivemap.bin').write_bytes(b'archive')
        self.metadata = {'TITLE_ID': 'CUSA00076', 'TITLE': 'The Order: 1886', 'APP_VER': '01.00'}
        self.sfo = patch.object(order1886.prepare, 'load_sfo', return_value=self.metadata)
        self.sfo.start()
        self.addCleanup(self.sfo.stop)

    def test_rejects_another_title_before_preparation(self):
        self.metadata['TITLE_ID'] = 'CUSA01623'
        with self.assertRaisesRegex(ValueError, 'Expected CUSA00076'):
            order1886.inspect_game(self.game)

    def test_names_empty_or_missing_game_files(self):
        (self.game / 'eboot.bin').write_bytes(b'')
        with self.assertRaisesRegex(ValueError, 'eboot.bin'):
            order1886.inspect_game(self.game)

    def test_requires_archive_and_content_directory(self):
        (self.game / 'archivemap.bin').unlink()
        with self.assertRaisesRegex(ValueError, 'content is incomplete'):
            order1886.inspect_game(self.game)

    def test_preparation_cannot_write_inside_original_dump(self):
        with self.assertRaisesRegex(ValueError, 'outside the game folder'):
            order1886.prepare_game(self.game, self.game / 'prepared')

    def test_cached_image_reused_only_while_source_and_output_match(self):
        out = self.user / 'prepared'
        def link(_game, target):
            (target / 'boot-linked.bin').write_bytes(b'linked image')
        with patch.object(order1886.prepare, 'prepare') as prepare, \
                patch.object(order1886.link_modules, 'link', side_effect=link) as linker:
            order1886.prepare_game(self.game, out)
            order1886.prepare_game(self.game, out)
            self.assertEqual(prepare.call_count, 1)
            (self.game / 'eboot.bin').write_bytes(b'new executable revision')
            order1886.prepare_game(self.game, out)
            self.assertEqual(prepare.call_count, 2)
            (out / 'boot-linked.bin').write_bytes(b'corrupted cached image')
            order1886.prepare_game(self.game, out)
            self.assertEqual(linker.call_count, 3)
            saved = json.loads((out / 'prepared.json').read_text())
            self.assertEqual(saved['image_sha256'], order1886.sha256(out / 'boot-linked.bin'))

    def test_interrupted_preparation_invalidates_previous_manifest(self):
        out = self.user / 'prepared'
        out.mkdir()
        (out / 'prepared.json').write_text('{"inputs": {}}')
        with patch.object(order1886.prepare, 'prepare', side_effect=RuntimeError('interrupted')):
            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                order1886.prepare_game(self.game, out)
        self.assertFalse((out / 'prepared.json').exists())

    def test_only_explicit_runtime_tuning_is_forwarded(self):
        inherited = {'PATH': 'original-path', 'SystemRoot': os.environ.get('SystemRoot', ''),
                     'ORDER1886_PATCHES': 'obsolete-patches.bin', 'UNRELATED_APP_SETTING': '1',
                     'ORDER1886_UNKNOWN': 'stale', 'ORDER1886_UPSCALER': 'fsr31',
                     'ORDER1886_USER_DIR': 'obsolete-save-directory'}
        before = dict(inherited)
        runtime = self.base / 'runtime binaries' / 'probe.exe'
        env = order1886.runtime_environment(runtime, self.user, inherited=inherited)
        self.assertEqual(inherited, before)
        self.assertNotIn('ORDER1886_PATCHES', env)
        self.assertEqual(env['UNRELATED_APP_SETTING'], '1')
        self.assertNotIn('ORDER1886_UNKNOWN', env)
        self.assertEqual(env['ORDER1886_GAME_PROFILE'], 'order1886')
        self.assertEqual(env['ORDER1886_USER_DIR'], str(self.user.resolve()))
        self.assertEqual(env['ORDER1886_GPU_USER_DIR'], str(self.user.resolve() / 'gpu' / order1886.SHADER_CACHE_ABI))
        self.assertEqual(env['ORDER1886_CONFIG'], str(self.user.resolve() / 'runtime.ini'))
        for retired in ('UPSCALER', 'OBJECT_MOTION', 'OBJECT_MOTION_ALL', 'SQUARE_PASS',
                        'JITTER', 'REACTIVE', 'STALE_READBACK'):
            self.assertNotIn('ORDER1886_' + retired, env)
        self.assertEqual(env['ORDER1886_FPS_LIMIT'], '30')
        self.assertEqual(env['PATH'], str(runtime.parent.resolve()) + os.pathsep + 'original-path')

    def test_arguments_preserve_spaces_and_exclude_patches(self):
        runtime = self.base / 'runtime binaries' / 'probe.exe'
        image = self.user / 'prepared' / 'boot-linked.bin'
        command = order1886.build_command(runtime, image, self.game, self.user, True)
        self.assertEqual(command[0:2], [str(runtime.resolve()), str(image.resolve())])
        self.assertEqual(command[command.index('--app0') + 1], str(self.game.resolve()))
        self.assertEqual(command[command.index('--user') + 1], str(self.user.resolve()))
        self.assertIn('--check-imports', command)
        self.assertNotIn('--patches', command)
        self.assertNotIn('--content-profile', command)

    def test_config_uses_native_resolution_and_30fps_baseline(self):
        order1886.write_runtime_config(self.user, {'display_mode': 'borderless', 'vsync': False})
        config = (self.user / 'runtime.ini').read_text()
        for expected in ('display_mode=borderless', 'vsync=0', 'fps_limit=30',
                         'render_resolution=native', 'frames_queued=1'):
            self.assertIn(expected + '\n', config)
        for retired in ('upscaler', 'object_motion', 'jitter', 'reactive', 'enemy_health_bar',
                        'stale_readback', 'live_resolution', 'overlay_upscaler'):
            self.assertNotIn(retired + '=', config)
        with self.assertRaisesRegex(ValueError, 'display mode'):
            order1886.write_runtime_config(self.user, {'display_mode': 'invalid'})

    def test_missing_explicit_runtime_is_reported(self):
        with self.assertRaisesRegex(ValueError, 'Runtime executable not found'):
            order1886.find_runtime(self.base / 'missing.exe')

    def test_lock_blocks_concurrent_session_and_releases_after_failure(self):
        with self.assertRaisesRegex(ValueError, 'fixture failure'):
            with order1886.session_lock(self.user):
                with self.assertRaisesRegex(RuntimeError, 'already running'):
                    with order1886.session_lock(self.user):
                        self.fail('second session acquired the same lock')
                raise ValueError('fixture failure')
        with order1886.session_lock(self.user):
            pass

    def test_child_exit_and_output_are_preserved(self):
        env = dict(os.environ, ORDER1886_USER_DIR=str(self.user))
        log = self.user / 'child.log'
        result = order1886.run_process([sys.executable, '-c', 'print("fixture output"); raise SystemExit(7)'], env, log, 10)
        self.assertEqual(result['exit_code'], 7)
        self.assertFalse(result['timed_out'])
        self.assertIn('fixture output', log.read_text())

    def test_watchdog_kills_and_reaps_child(self):
        env = dict(os.environ, ORDER1886_USER_DIR=str(self.user))
        processes = []
        popen = subprocess.Popen
        def capture(*args, **kwargs):
            process = popen(*args, **kwargs)
            processes.append(process)
            return process
        with patch.object(order1886.subprocess, 'Popen', side_effect=capture):
            result = order1886.run_process([sys.executable, '-c', 'import time; time.sleep(30)'], env,
                                          self.user / 'timeout.log', timeout=0.15)
        self.assertTrue(result['timed_out'])
        self.assertEqual(result['exit_code'], 124)
        self.assertIsNotNone(processes[0].poll())
        self.assertLess(result['elapsed_seconds'], 10)

    def test_default_runtime_stays_inside_selected_installation(self):
        install = self.base / 'portable package'
        source = self.base / 'source'
        reference = self.base / 'foreign runtime' / 'unrelated-build' / 'bin' / 'order1886-runtime.exe'
        reference.parent.mkdir(parents=True)
        reference.write_bytes(b'reference')
        with patch.object(order1886, 'INSTALL_ROOT', install), patch.object(order1886, 'ROOT', source):
            self.assertIsNone(order1886.find_runtime())
            packaged = install / 'bin' / 'order1886-runtime.exe'
            packaged.parent.mkdir(parents=True)
            packaged.write_bytes(b'packaged')
            order1886.write_json(packaged.with_name('runtime-build.json'), {
                'runtime_sha256': order1886.sha256(packaged), 'game_profile': 'order1886',
                'runtime_abi': order1886.RUNTIME_ABI})
            self.assertEqual(order1886.find_runtime(), packaged.resolve())

    def test_explicit_runtime_rejects_stale_or_unidentified_build(self):
        runtime = self.base / 'old-runtime.exe'
        runtime.write_bytes(b'old')
        with self.assertRaisesRegex(ValueError, 'dedicated Order runtime'):
            order1886.find_runtime(runtime)
        order1886.write_json(runtime.with_name('runtime-build.json'), {
            'runtime_sha256': order1886.sha256(runtime), 'game_profile': 'order1886'})
        with self.assertRaisesRegex(ValueError, 'dedicated Order runtime'):
            order1886.find_runtime(runtime)

    def test_stop_request_reaps_child_and_records_forced_cleanup(self):
        stop = self.user / 'stop-request'
        timer = threading.Timer(0.15, lambda: stop.write_text('stop'))
        timer.start()
        self.addCleanup(timer.join)
        with patch.object(order1886, 'request_runtime_close', return_value=False):
            result = order1886.run_process(
                [sys.executable, '-c', 'import time; time.sleep(30)'],
                dict(os.environ, ORDER1886_USER_DIR=str(self.user)), self.user / 'stop.log',
                timeout=10, stop_file=stop, stop_grace_seconds=0.05)
        self.assertTrue(result['stop_requested'])
        self.assertTrue(result['forced_stop'])
        self.assertFalse(result['timed_out'])
        self.assertEqual(result['exit_code'], 130)

    def test_runtime_build_metadata_must_match_executable(self):
        runtime = self.base / 'order1886-runtime.exe'
        runtime.write_bytes(b'new build')
        build = runtime.with_name('runtime-build.json')
        order1886.write_json(build, {'runtime_sha256': 'stale', 'source_revision': 'old'})
        self.assertIsNone(order1886.runtime_identity(runtime)['build'])
        order1886.write_json(build, {'runtime_sha256': order1886.sha256(runtime), 'source_revision': 'new'})
        self.assertEqual(order1886.runtime_identity(runtime)['build']['source_revision'], 'new')

    def test_cli_rejects_state_under_game_before_creating_it(self):
        state = self.game / 'forbidden-state'
        self.assertEqual(order1886.main(['--game-dir', str(self.game), '--state-dir', str(state), '--prepare-only']), 2)
        self.assertFalse(state.exists())


if __name__ == '__main__':
    unittest.main()
