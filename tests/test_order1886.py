"""Order-specific safety and lifecycle tests; these do not claim game compatibility."""
from paths import ROOT
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import order1886


class InvalidConsole:
    def __init__(self, trigger=None):
        self.trigger = trigger

    def write(self, text):
        if self.trigger is None or self.trigger in text:
            raise OSError(22, 'Invalid argument: detached console')
        return len(text)

    def flush(self):
        pass


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
                     'ORDER1886_PREP_WORKERS': '8',
                     'ORDER1886_DIAG_RESOURCE_SHARPS': '1',
                     'ORDER1886_USER_DIR': 'obsolete-save-directory'}
        before = dict(inherited)
        runtime = self.base / 'runtime binaries' / 'probe.exe'
        env = order1886.runtime_environment(runtime, self.user, inherited=inherited)
        self.assertEqual(inherited, before)
        self.assertNotIn('ORDER1886_PATCHES', env)
        self.assertEqual(env['UNRELATED_APP_SETTING'], '1')
        self.assertNotIn('ORDER1886_UNKNOWN', env)
        self.assertEqual(env['ORDER1886_DIAG_RESOURCE_SHARPS'], '1')
        self.assertEqual(env['ORDER1886_GAME_PROFILE'], 'order1886')
        self.assertEqual(env['ORDER1886_USER_DIR'], str(self.user.resolve()))
        self.assertEqual(env['ORDER1886_GPU_USER_DIR'], str(self.user.resolve() / 'gpu' / order1886.SHADER_CACHE_ABI))
        self.assertEqual(env['ORDER1886_CONFIG'], str(self.user.resolve() / 'runtime.ini'))
        for retired in ('UPSCALER', 'OBJECT_MOTION', 'OBJECT_MOTION_ALL', 'SQUARE_PASS',
                        'JITTER', 'REACTIVE', 'STALE_READBACK'):
            self.assertNotIn('ORDER1886_' + retired, env)
        self.assertEqual(env['ORDER1886_FPS_LIMIT'], '30')
        self.assertEqual(env['ORDER1886_PREP_WORKERS'], '0')
        self.assertEqual(env['PATH'], str(runtime.parent.resolve()) + os.pathsep + 'original-path')

    def test_frame_rate_host_cap_and_config_match_without_changing_vblank(self):
        for rate in (30, 60):
            with self.subTest(rate=rate):
                settings = {'frame_rate': rate}
                env = order1886.runtime_environment(self.base / 'runtime.exe', self.user, settings)
                self.assertEqual(env['ORDER1886_FPS_LIMIT'], str(rate))
                self.assertEqual(env['ORDER1886_VBLANK_HZ'], '60')
                order1886.write_runtime_config(self.user, settings)
                self.assertIn(f'fps_limit={rate}\n', (self.user / 'runtime.ini').read_text())
        with self.assertRaisesRegex(ValueError, '30, 60 or 90'):
            order1886.write_runtime_config(self.user, {'frame_rate': 120})

    def test_launcher_language_codes_use_orbis_system_language_ids(self):
        self.assertEqual(order1886.SYSTEM_LANGUAGES,
                         {'en': 1, 'ru': 8, 'ar': 21, 'es': 3, 'pt': 17, 'fr': 2,
                          'de': 4, 'it': 5, 'pl': 16, 'tr': 19, 'zh': 11, 'ja': 0, 'ko': 9})

    def test_system_language_is_explicit_and_does_not_inherit_stale_tuning(self):
        inherited = {'ORDER1886_LANGUAGE': '8', 'PATH': ''}
        runtime = self.base / 'runtime.exe'
        self.assertEqual(order1886.runtime_environment(runtime, self.user, inherited=inherited)
                         ['ORDER1886_LANGUAGE'], '1')
        for language in range(30):
            with self.subTest(language=language):
                env = order1886.runtime_environment(runtime, self.user,
                                                   {'system_language': language}, inherited)
                self.assertEqual(env['ORDER1886_LANGUAGE'], str(language))
        self.assertEqual(inherited['ORDER1886_LANGUAGE'], '8')
        for language in (-1, 30, True, 8.0, '8', None):
            with self.subTest(language=language), self.assertRaisesRegex(ValueError, 'language'):
                order1886.runtime_environment(runtime, self.user, {'system_language': language})

    def test_system_language_cli_rejects_invalid_ids_before_preparation(self):
        for language in ('-1', '30', '8oops'):
            with self.subTest(language=language), patch.object(order1886, 'prepare_game') as prepare, \
                    self.assertRaises(SystemExit) as stopped:
                order1886.main(['--system-language', language])
            self.assertEqual(stopped.exception.code, 2)
            prepare.assert_not_called()

    def test_system_language_cli_reaches_runtime_and_diagnostics(self):
        runtime = self.base / 'runtime.exe'
        runtime.write_bytes(b'identified fixture')

        def finish(command, env, log, *args):
            Path(log).write_text('CPU-only fixture\n')
            self.assertEqual(env['ORDER1886_LANGUAGE'], str(expected))
            return {'exit_code': 0, 'runtime_exit_code': 0, 'timed_out': False,
                    'stop_requested': False, 'forced_stop': False, 'elapsed_seconds': 0}

        for choice, expected in ((None, 1), (8, 8), (0, 0), (17, 17)):
            with self.subTest(choice=choice), \
                    patch.object(order1886, 'find_runtime', return_value=runtime), \
                    patch.object(order1886, 'prepare_game', return_value={'image_sha256': 'fixture'}), \
                    patch.object(order1886.save_backup, 'backup'), \
                    patch.object(order1886, 'run_process', side_effect=finish):
                args = ['--game-dir', str(self.game), '--state-dir', str(self.user)]
                if choice is not None:
                    args += ['--system-language', str(choice)]
                self.assertEqual(order1886.main(args), 0)
                report = json.loads((self.user / 'logs/last-run.json').read_text())
                self.assertEqual(report['settings']['system_language'], expected)
                self.assertEqual(report['runtime_environment']['ORDER1886_LANGUAGE'], str(expected))

    def test_frame_rate_cli_requires_a_verified_matching_60_receipt(self):
        good = {**order1886.timing.recipe(60), 'recipe_sha256': order1886.timing.recipe_sha256(60),
                'applied': True, 'source_verified': True}
        for profile, expected in (({}, 2), ({**good, 'host_fps_limit': 30}, 2), (good, 0)):
            with self.subTest(profile=profile), patch.object(order1886, 'prepare_game',
                    return_value={'image_sha256': 'fixture', 'frame_rate_profile': profile}) as prepare:
                self.assertEqual(order1886.main(['--game-dir', str(self.game), '--state-dir', str(self.user),
                                                 '--prepare-only', '--frame-rate', '60']), expected)
                prepare.assert_called_once_with(self.game.resolve(), self.user.resolve() / 'prepared',
                                                frame_rate=60, aspect_ratio='original', patches=[])

    def test_frame_rate_60_unknown_hash_does_not_change_existing_cache(self):
        out = self.user / 'prepared'
        out.mkdir()
        (out / 'prepared.json').write_text('{"previous": "preserve"}')
        (out / 'boot-linked.bin').write_bytes(b'previous valid image')
        before = {p.name: p.read_bytes() for p in out.iterdir()}
        with self.assertRaisesRegex(ValueError, 'SELF SHA256'):
            order1886.prepare_game(self.game, out, frame_rate=60)
        self.assertEqual({p.name: p.read_bytes() for p in out.iterdir()}, before)

    def test_fullscreen_cli_requires_matching_verified_aspect_receipt(self):
        good = {**order1886.display.recipe('16:9'), 'recipe_sha256': order1886.display.recipe_sha256('16:9'),
                'applied': True, 'source_verified': True}
        for profile, expected in (({}, 2), ({**good, 'source_verified': False}, 2), (good, 0)):
            with self.subTest(profile=profile), patch.object(order1886, 'prepare_game',
                    return_value={'image_sha256': 'fixture', 'display_profile': profile}) as prepare:
                self.assertEqual(order1886.main(['--game-dir', str(self.game), '--state-dir', str(self.user),
                                                 '--prepare-only', '--aspect-ratio', '16:9']), expected)
                prepare.assert_called_once_with(self.game.resolve(), self.user.resolve() / 'prepared',
                                                frame_rate=30, aspect_ratio='16:9', patches=[])

    def test_frame_rate_cache_30_60_30_rebuilds_and_preserves_source(self):
        import shutil
        from test_order1886_frame_rate import write_boot_fixture, verified_fixture_source, METADATA, SITE_RVA
        self.metadata.update(METADATA)
        out = self.user / 'prepared'
        original = (self.game / 'eboot.bin').read_bytes()

        def prepare(_game, target):
            write_boot_fixture(target / 'boot.bin')

        def link(_game, target):
            shutil.copyfile(target / 'boot.bin', target / 'boot-linked.bin')

        with verified_fixture_source(self.game / 'eboot.bin'), \
                patch.object(order1886.prepare, 'prepare', side_effect=prepare) as preparer, \
                patch.object(order1886.link_modules, 'link', side_effect=link):
            results = [order1886.prepare_game(self.game, out, frame_rate=30),
                       order1886.prepare_game(self.game, out, frame_rate=60),
                       order1886.prepare_game(self.game, out, frame_rate=60),
                       order1886.prepare_game(self.game, out, frame_rate=30)]
        self.assertEqual(preparer.call_count, 3)
        self.assertEqual([r['frame_rate_profile']['applied'] for r in results], [False, True, True, False])
        self.assertNotEqual(results[0]['inputs'], results[1]['inputs'])
        self.assertEqual(results[0]['inputs'], results[-1]['inputs'])
        self.assertIn('tool/order1886_frame_rate.py', results[0]['inputs'])
        self.assertEqual(results[1]['inputs']['host_fps_limit'], 60)
        self.assertEqual(results[1]['inputs']['runtime_abi'], order1886.RUNTIME_ABI)
        self.assertEqual((self.game / 'eboot.bin').read_bytes(), original)
        self.assertEqual((out / 'boot.bin').read_bytes()[56 + 24 + 128 + 32 + SITE_RVA + 6], 2)

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

    def test_presentation_filter_config_defaults_linear_override_and_rejection(self):
        for settings, expected in (({}, 'fsr1'), ({'presentation_filter': 'linear'}, 'linear')):
            with self.subTest(settings=settings):
                order1886.write_runtime_config(self.user, settings)
                config = (self.user / 'runtime.ini').read_text()
                self.assertIn(f'presentation_filter={expected}\n', config)
                self.assertIn('render_resolution=native\n', config)
                self.assertIn('fps_limit=30\n', config)
        with self.assertRaisesRegex(ValueError, 'presentation filter'):
            order1886.write_runtime_config(self.user, {'presentation_filter': 'fsr3'})

    def test_presentation_filter_cli_reaches_config_and_diagnostics(self):
        runtime = self.base / 'runtime.exe'
        runtime.write_bytes(b'identified fixture')

        def finish(command, env, log, *args):
            Path(log).write_text('CPU-only fixture\n')
            self.assertNotIn('ORDER1886_PRESENTATION_FILTER', env)
            self.assertEqual(env['ORDER1886_FPS_LIMIT'], '30')
            return {'exit_code': 0, 'runtime_exit_code': 0, 'timed_out': False,
                    'stop_requested': False, 'forced_stop': False, 'elapsed_seconds': 0}

        for choice, expected in ((None, 'fsr1'), ('linear', 'linear')):
            with self.subTest(choice=choice), \
                    patch.object(order1886, 'find_runtime', return_value=runtime), \
                    patch.object(order1886, 'prepare_game', return_value={'image_sha256': 'fixture'}), \
                    patch.object(order1886.save_backup, 'backup'), \
                    patch.object(order1886, 'run_process', side_effect=finish):
                args = ['--game-dir', str(self.game), '--state-dir', str(self.user)]
                if choice is not None:
                    args += ['--presentation-filter', choice]
                self.assertEqual(order1886.main(args), 0)
                self.assertIn(f'presentation_filter={expected}\n', (self.user / 'runtime.ini').read_text())
                report = json.loads((self.user / 'logs/last-run.json').read_text())
                self.assertEqual(report['settings']['presentation_filter'], expected)
                self.assertEqual(report['settings']['fps_limit'], 30)

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
        # Windows venv Python is a redirector; model the native runtime's direct child.
        host_python = getattr(sys, '_base_executable', sys.executable)
        log = self.user / 'timeout.log'
        ready = self.user / 'watchdog-child-ready'
        processes = []
        popen = subprocess.Popen
        def capture(*args, **kwargs):
            process = popen(*args, **kwargs)
            processes.append(process)
            # Exercise output draining after startup, even on a heavily loaded host.
            deadline = time.monotonic() + 5
            while not ready.exists():
                if process.poll() is not None:
                    self.fail('Watchdog fixture exited before signaling readiness')
                if time.monotonic() >= deadline:
                    process.kill()
                    process.wait(timeout=5)
                    self.fail('Watchdog fixture did not signal readiness')
                time.sleep(0.01)
            return process
        with patch.object(order1886.subprocess, 'Popen', side_effect=capture):
            result = order1886.run_process(
                [host_python, '-c', 'import os,time; from pathlib import Path; '
                 'print("fixture-pid=" + str(os.getpid()), flush=True); '
                 f'Path({str(ready)!r}).touch(); time.sleep(30)'],
                env, log, timeout=0.15)
        released_log = log.rename(self.user / 'released-timeout.log')
        self.assertTrue(result['timed_out'])
        self.assertEqual(result['exit_code'], 124)
        self.assertIsNotNone(processes[0].poll())
        self.assertLess(result['elapsed_seconds'], 10)
        self.assertIn(f'fixture-pid={processes[0].pid}\n', released_log.read_text())
        released_log.unlink()

    def test_default_runtime_stays_inside_selected_installation(self):
        runtime_name = 'order1886-runtime.exe' if os.name == 'nt' else 'order1886-runtime'
        install = self.base / 'portable package'
        source = self.base / 'source'
        reference = self.base / 'foreign runtime' / 'unrelated-build' / 'bin' / runtime_name
        reference.parent.mkdir(parents=True)
        reference.write_bytes(b'reference')
        with patch.object(order1886, 'INSTALL_ROOT', install), patch.object(order1886, 'ROOT', source):
            self.assertIsNone(order1886.find_runtime())
            packaged = install / 'bin' / runtime_name
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
        host_python = getattr(sys, '_base_executable', sys.executable)
        log = self.user / 'stop.log'
        stop = self.user / 'stop-request'
        timer = threading.Timer(0.15, lambda: stop.write_text('stop'))
        timer.start()
        self.addCleanup(timer.join)
        with patch.object(order1886, 'request_runtime_close', return_value=False):
            result = order1886.run_process(
                [host_python, '-c', 'import time; time.sleep(30)'],
                dict(os.environ, ORDER1886_USER_DIR=str(self.user)), log,
                timeout=10, stop_file=stop, stop_grace_seconds=0.05)
        log.rename(self.user / 'released-stop.log').unlink()
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


    def test_invalid_console_at_final_status_preserves_native_exit_and_diagnostics(self):
        runtime = self.base / 'runtime.exe'
        runtime.write_bytes(b'identified fixture')
        for native_exit in (0, 23):
            with self.subTest(native_exit=native_exit):
                status = 'failed' if native_exit else 'process_exited'
                reason = 'STOP: intentional native failure' if native_exit else None
                command = [sys.executable, '-c', f'print({(reason or "native success")!r}); raise SystemExit({native_exit})']
                with patch.object(order1886, 'find_runtime', return_value=runtime), \
                        patch.object(order1886, 'prepare_game', return_value={'image_sha256': 'fixture'}), \
                        patch.object(order1886, 'build_command', return_value=command), \
                        patch.object(order1886.save_backup, 'backup'), \
                        patch.object(sys, 'stdout', InvalidConsole(f'Runtime {status}; exit')), \
                        patch.object(sys, 'stderr', InvalidConsole()):
                    code = order1886.main(['--game-dir', str(self.game), '--state-dir', str(self.user)])
                self.assertEqual(code, native_exit)
                report = json.loads((self.user / 'logs/last-run.json').read_text())
                self.assertEqual(report['status'], status)
                self.assertEqual(report['exit_code'], native_exit)
                self.assertEqual(report['stop_reason'], reason)
                diagnostic = (self.user / 'logs/backend.log').read_text()
                self.assertIn(f'Runtime {status}; exit {native_exit}.', diagnostic)
                self.assertIn(report['log'], diagnostic)

    def test_invalid_console_before_runtime_wait_cannot_orphan_child(self):
        children = []
        popen = subprocess.Popen

        def capture(*args, **kwargs):
            child = popen(*args, **kwargs)
            children.append(child)
            return child

        try:
            with patch.object(order1886.subprocess, 'Popen', side_effect=capture), \
                    patch.object(sys, 'stdout', InvalidConsole()):
                result = order1886.run_process(
                    [sys.executable, '-c', "print('native failure'); raise SystemExit(23)"],
                    dict(os.environ, ORDER1886_USER_DIR=str(self.user)), self.user / 'console.log', timeout=10)
            self.assertEqual(result['exit_code'], 23)
            self.assertIsNotNone(children[0].returncode)
            self.assertIn('Runtime started (PID', (self.user / 'console.log').read_text())
            self.assertIn('native failure', (self.user / 'console.log').read_text())
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.wait()

    def test_invalid_console_error_handler_keeps_validation_error_in_log(self):
        with patch.object(sys, 'stdout', InvalidConsole()), patch.object(sys, 'stderr', InvalidConsole()):
            code = order1886.main(['--game-dir', str(self.base / 'missing-game'),
                                   '--state-dir', str(self.user)])
        self.assertEqual(code, 2)
        self.assertIn('Missing or empty game file:', (self.user / 'logs/backend.log').read_text())


if __name__ == '__main__':
    unittest.main()
