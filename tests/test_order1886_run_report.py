"""A capture's own report must say which configuration produced it."""
from pathlib import Path
from unittest.mock import patch
import json
import tempfile
import unittest

import order1886

ROOT = Path(__file__).resolve().parents[1]
METADATA = {'TITLE': 'The Order: 1886', 'TITLE_ID': 'CUSA00076', 'APP_VER': '01.00',
            'VERSION': '01.03'}


def runtime_with(state, **build):
    import hashlib
    runtime = state / 'runtime.exe'
    runtime.write_bytes(b'native fixture')
    receipt = {'runtime_sha256': hashlib.sha256(runtime.read_bytes()).hexdigest(),
               'game_profile': 'order1886', 'runtime_abi': order1886.RUNTIME_ABI}
    receipt.update(build)
    runtime.with_name('runtime-build.json').write_text(json.dumps(receipt))
    return runtime


def prepared(**overrides):
    # main re-checks the 60 FPS receipt, so the prepared result must look verified.
    base = {'image_sha256': 'fixture',
            'frame_rate_profile': {'engine_fps': 60, 'host_fps_limit': 60, 'applied': True,
                                   'source_verified': True,
                                   'recipe_sha256': order1886.timing.recipe_sha256(60)},
            'display_profile': {'aspect_ratio': '16:9'}, 'catalogue_patches': []}
    base.update(overrides)
    return base


class ReportConfigurationTests(unittest.TestCase):
    def run_backend(self, state, extra, prepared_result):
        game = state / 'game'
        game.mkdir()
        for name in order1886.REQUIRED_FILES:
            target = game / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'fixture')
        (game / '_data').mkdir()
        (game / 'archivemap.bin').write_bytes(b'archive')
        runtime = runtime_with(state, htile_control=True, effect_toggles=True)
        log = state / 'run.log'
        args = ['--game-dir', str(game), '--state-dir', str(state)] + extra

        def finish(command, env, logfile, *rest):
            logfile.write_text('fixture exit')
            return {'exit_code': 0, 'timed_out': False, 'stop_requested': False,
                    'forced_stop': False, 'elapsed_seconds': 0.1}

        with patch.object(order1886, 'inspect_game', return_value=METADATA), \
             patch.object(order1886, 'find_runtime', return_value=runtime), \
             patch.object(order1886, 'prepare_game', return_value=prepared_result), \
             patch.object(order1886.save_backup, 'backup'), \
             patch.object(order1886, 'run_process', side_effect=finish):
            code = order1886.main(args)
        report = json.loads((state / 'logs/last-run.json').read_text())
        return code, report

    def test_the_report_records_the_presentation_and_switches(self):
        with tempfile.TemporaryDirectory() as temporary:
            code, report = self.run_backend(
                Path(temporary), ['--frame-rate', '60', '--fps-cap', '30', '--htile',
                                  '--in-game-menu', '--texture-update-locking'],
                prepared())
            self.assertEqual(code, 0)
            configuration = report['configuration']
            self.assertEqual(configuration['timing']['engine_fps'], 60)
            self.assertEqual(configuration['timing']['fps_limit'], 30)
            self.assertEqual(report['settings']['fps_limit'], 30,
                             'the recorded limit must be the one applied, not the engine rate')
            self.assertIs(configuration['switches']['htile_unqualified'], True)
            self.assertIs(configuration['switches']['in_game_menu'], True)
            self.assertEqual(configuration['switches']['readbacks'], 'relaxed')
            self.assertNotEqual(configuration['switches']['effect_toggles'], 0)

    def test_the_report_records_the_catalogue_patches_that_were_applied(self):
        with tempfile.TemporaryDirectory() as temporary:
            applied = [{'id': 'order1886-test-recipe', 'recipe_sha256': 'abc',
                        'edits': [{'offset': '0x1c0', 'before': '00', 'after': '01'}]}]
            code, report = self.run_backend(Path(temporary), [], prepared(catalogue_patches=applied))
            self.assertEqual(code, 0)
            self.assertEqual([row['id'] for row in report['configuration']['catalogue_patches']],
                             ['order1886-test-recipe'])

    def test_a_quiet_launch_records_off_switches_rather_than_omitting_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            code, report = self.run_backend(Path(temporary), [], prepared())
            self.assertEqual(code, 0)
            switches = report['configuration']['switches']
            self.assertIs(switches['htile_unqualified'], False)
            self.assertIs(switches['in_game_menu'], False)
            self.assertEqual(switches['effect_toggles'], 0)
            self.assertEqual(report['configuration']['catalogue_patches'], [])


if __name__ == '__main__':
    unittest.main()
