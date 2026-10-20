"""Live runtime switches stay off unless a matching runtime declares them and the player asks.

The runtime reads its own toggle file (ORDER1886_TOGGLE_FILE, re-read every 250 ms) as a
decimal mask of optimizations to switch off. These settings therefore deliver that file
and nothing else: the bits named here are the ones the Order renderer still reads
(gpu/shim/ps4_toggles.h, Ps4Toggle::Disabled call sites).
"""
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest

import order1886
from launcher import order1886_common as launcher
from launcher import order1886_worker as worker

ROOT = Path(__file__).resolve().parents[1]
# The mask values the header gives: Ps4Toggle::ThreadedRecording is 16 and
# Ps4Toggle::UpdateImageFastPath is 1 << 30 (the low names are masks, not bit indices).
RECORDING = 16
IMAGE_UPDATE = 1 << 30


def runtime_with(state, **build):
    runtime = state / 'runtime.exe'
    runtime.write_bytes(b'native fixture')
    receipt = {'runtime_sha256': hashlib.sha256(runtime.read_bytes()).hexdigest(),
               'game_profile': 'order1886', 'runtime_abi': order1886.RUNTIME_ABI}
    receipt.update(build)
    runtime.with_name('runtime-build.json').write_text(json.dumps(receipt))
    return runtime


def environment(runtime, state, settings):
    return order1886.runtime_environment(runtime, state, settings, {})


def toggle_file(state):
    return state.resolve() / order1886.EFFECT_TOGGLE_FILE


def header_toggles():
    """The mask values gpu/shim/ps4_toggles.h declares, read from the enum itself."""
    header = (ROOT / 'gpu' / 'shim' / 'ps4_toggles.h').read_text(encoding='utf-8')
    body = header.split('enum : std::uint64_t {', 1)[1].split('};', 1)[0]
    values = {}
    for match in re.finditer(r'(\w+)\s*=\s*([^,/]+)', body):
        expression = match.group(2).strip().replace('ull', '').replace('u', '').replace('l', '')
        values[match.group(1)] = int(eval(expression, {'__builtins__': {}}))  # noqa: S307
    return values


class EffectToggleTests(unittest.TestCase):
    def test_default_is_off_and_leaves_the_toggle_file_out_of_the_launch(self):
        for settings in ({}, {'synchronous_recording': False, 'texture_update_locking': False}):
            with self.subTest(settings=settings), tempfile.TemporaryDirectory() as temporary:
                state = Path(temporary)
                runtime = runtime_with(state, effect_toggles=True)
                # A mask from an earlier launch must not outlive an all-off launch.
                toggle_file(state).write_text(str(RECORDING), encoding='utf-8')
                env = environment(runtime, state, settings)
                self.assertNotIn('ORDER1886_TOGGLE_FILE', env)
                self.assertFalse(toggle_file(state).exists())

    def test_enabling_writes_the_exact_mask_the_runtime_re_reads(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            runtime = runtime_with(state, effect_toggles=True)
            env = environment(runtime, state, {'synchronous_recording': True})
            path = Path(env['ORDER1886_TOGGLE_FILE'])
            self.assertEqual(path, toggle_file(state))
            self.assertEqual(path.read_text(encoding='utf-8').strip(), str(RECORDING))
            env = environment(runtime, state, {'synchronous_recording': True,
                                               'texture_update_locking': True})
            self.assertEqual(path.read_text(encoding='utf-8').strip(),
                             str(RECORDING | IMAGE_UPDATE))
            env = environment(runtime, state, {'synchronous_recording': False,
                                               'texture_update_locking': True})
            self.assertEqual(path.read_text(encoding='utf-8').strip(), str(IMAGE_UPDATE))

    def test_only_real_booleans_are_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            runtime = runtime_with(state, effect_toggles=True)
            for key in ('synchronous_recording', 'texture_update_locking'):
                for invalid in ('on', 1, None, [True]):
                    with self.subTest(key=key, invalid=invalid), self.assertRaises(ValueError):
                        environment(runtime, state, {key: invalid})
                self.assertFalse(toggle_file(state).exists())

    def test_a_runtime_without_the_declaration_refuses_the_enabled_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            runtime = runtime_with(state)
            for key in ('synchronous_recording', 'texture_update_locking'):
                with self.subTest(key=key), self.assertRaises(ValueError) as raised:
                    environment(runtime, state, {key: True})
                self.assertIn('Effect toggles require', str(raised.exception))
                self.assertIn('Rebuild or select a newer runtime', str(raised.exception))
                self.assertFalse(toggle_file(state).exists())
            env = environment(runtime, state, {'synchronous_recording': False})
            self.assertNotIn('ORDER1886_TOGGLE_FILE', env)

    def test_the_catalog_exposes_both_options_off_by_default(self):
        for key in ('synchronous_recording', 'texture_update_locking'):
            with self.subTest(key=key):
                field = next(item for item in worker.FIELDS if item['key'] == key)
                self.assertIs(field['default'], False)
                self.assertEqual(field['kind'], 'boolean')
                self.assertEqual(field['page'], 'performance')
                self.assertTrue(field['available'])
                self.assertEqual(field['apply'], 'next_launch')
                self.assertIn('unqualified', field['description'].lower())

    def test_no_model_detail_or_lod_control_is_exposed(self):
        # The renderer has no level-of-detail control, so no setting may claim one.
        for item in worker.FIELDS:
            if item['key'] == 'model_detail':
                self.assertFalse(item['available'])
            self.assertNotIn('lod', item['key'])
            self.assertNotIn('lod ', item['description'].lower())

    def test_the_exposed_bits_are_the_header_bits_and_the_renderer_reads_them(self):
        declared = header_toggles()
        sources = '\n'.join(path.read_text(encoding='utf-8', errors='replace')
                            for path in (ROOT / 'gpu').rglob('*')
                            if path.suffix in ('.cpp', '.h') and 'third_party' not in path.parts)
        expected = {'synchronous_recording': 'ThreadedRecording',
                    'texture_update_locking': 'UpdateImageFastPath'}
        for key, (bit, _label) in order1886.EFFECT_TOGGLES.items():
            with self.subTest(key=key):
                self.assertEqual(bit, declared[expected[key]])
                self.assertIn('Disabled(Ps4Toggle::' + expected[key], sources)
        # Declared in the header but read by nothing: no setting may offer them.
        for name in ('SceneHalfRes', 'TaaTonemapBlend', 'TaaClip', 'TaaVariance', 'TaaFilter'):
            self.assertNotIn('Disabled(Ps4Toggle::' + name, sources)

    def test_the_launch_command_carries_an_enabled_setting_to_the_backend(self):
        values = launcher.load_launch_settings(ROOT / 'out' / 'state',
                                               {'game_dir': str(ROOT / 'out' / 'game')})
        self.assertFalse(values['synchronous_recording'])
        self.assertFalse(values['texture_update_locking'])
        command = launcher.backend_command(values)
        self.assertNotIn('--synchronous-recording', command)
        self.assertNotIn('--texture-update-locking', command)
        values.update(synchronous_recording=True, texture_update_locking=True)
        command = launcher.backend_command(values)
        self.assertIn('--synchronous-recording', command)
        self.assertIn('--texture-update-locking', command)
        parsed = order1886.argument_parser().parse_args(
            ['--synchronous-recording', '--texture-update-locking'])
        self.assertIs(parsed.synchronous_recording, True)
        self.assertIs(parsed.texture_update_locking, True)

    def test_the_setting_round_trips_through_the_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            runtime = runtime_with(state, effect_toggles=True)
            app = worker.Worker(state, ROOT)
            app.dispatch('settings.set', {'values': {'runtime': str(runtime)}})
            values = app.dispatch('settings.set',
                                  {'values': {'synchronous_recording': True}})['settings']
            self.assertIs(values['synchronous_recording'], True)
            saved = json.loads((state / 'settings.json').read_text(encoding='utf-8'))
            self.assertIs(saved['synchronous_recording'], True)
            self.assertIs(launcher.load_launch_settings(state)['synchronous_recording'], True)
            env = order1886.runtime_environment(runtime, state, app.settings(), {})
            self.assertEqual(Path(env['ORDER1886_TOGGLE_FILE']).read_text(encoding='utf-8').strip(),
                             str(RECORDING))
            values = app.dispatch('settings.set',
                                  {'values': {'synchronous_recording': False}})['settings']
            self.assertIs(values['synchronous_recording'], False)
            self.assertIs(launcher.load_launch_settings(state)['synchronous_recording'], False)

    def test_the_worker_refuses_the_option_for_a_runtime_without_the_declaration(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            runtime = runtime_with(state)
            app = worker.Worker(state, ROOT)
            app.dispatch('settings.set', {'values': {'runtime': str(runtime)}})
            with self.assertRaises(ValueError):
                app.dispatch('settings.set', {'values': {'texture_update_locking': True}})
            values = app.dispatch('state.get', {})['settings']
            self.assertIs(values['texture_update_locking'], False)


if __name__ == '__main__':
    unittest.main()
