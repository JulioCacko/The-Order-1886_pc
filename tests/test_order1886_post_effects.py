"""Post-effect switches (#16): hash-gated edits of the prepared image, never the game folder."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from paths import ROOT

sys.path.insert(0, str(ROOT / 'scripts'))
import order1886
import order1886_frame_rate as timing
import order1886_post_effects as effects
import prepare
from launcher import order1886_common as launcher
from launcher import order1886_worker as worker

METADATA = dict(timing.EXPECTED_METADATA)
# The extracted game sits next to the checkout, or above it for a worktree.
GAME = next((base / 'ShadPs4Plus-PkgExtractor-1.1-windows' / 'CUSA00076' for base in (ROOT, *ROOT.parents)
             if (base / 'ShadPs4Plus-PkgExtractor-1.1-windows' / 'CUSA00076' / 'eboot.bin').is_file()), ROOT)
SITES = [(name, rva, bytes.fromhex(expected), bytes.fromhex(replacement))
         for name, (_label, edits) in effects.EFFECTS.items() for rva, expected, replacement in edits]


def fixture(path):
    """A PS4BOOT2 container of the verified size holding every expected instruction."""
    start = timing.HEADER.size + 24 + 128 + 32
    with path.open('wb') as stream:
        stream.write(timing.HEADER.pack(b'PS4BOOT2', timing.EXPECTED_IMAGE_SIZE, 0xa0, 1, 1, 1, 1))
        stream.write(b'\0' * (24 + 128 + 32))
        stream.seek(start + timing.EXPECTED_IMAGE_SIZE - 1)
        stream.write(b'\0')
        for _name, rva, expected, _replacement in SITES:
            stream.seek(start + rva)
            stream.write(expected)
    return start


class PostEffectPreparationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.source = self.base / 'original eboot.bin'
        self.source.write_bytes(b'original fixture')
        elf = b'reconstructed ELF fixture'
        for target, value in ((timing, ('EXPECTED_SELF_SHA256', hashlib.sha256(self.source.read_bytes()).hexdigest())),
                              (timing, ('EXPECTED_ELF_SHA256', hashlib.sha256(elf).hexdigest())),
                              (timing.prepare, ('parse_self', lambda data: (elf, None, None, None, None)))):
            patcher = patch.object(target, *value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_all_on_never_touches_a_missing_derived_image(self):
        profile = effects.validate_source(self.source, [], {})
        result = effects.apply_prepared(self.base / 'absent.bin', profile)
        self.assertFalse(result['applied'])
        self.assertEqual(result['disabled'], [])

    def test_each_effect_changes_only_its_own_sites(self):
        for name in effects.EFFECTS:
            with self.subTest(effect=name):
                boot = self.base / f'{name}.bin'
                start = fixture(boot)
                before = boot.read_bytes()
                original = self.source.read_bytes()
                result = effects.apply_prepared(boot, effects.validate_source(self.source, [name], METADATA))
                after = boot.read_bytes()
                mine = [site for site in SITES if site[0] == name]
                expected = bytearray(before)
                for _name, rva, _old, replacement in mine:
                    expected[start + rva:start + rva + len(replacement)] = replacement
                self.assertEqual(after, bytes(expected))
                self.assertEqual(self.source.read_bytes(), original)
                self.assertTrue(result['applied'])
                self.assertEqual(result['changed_bytes'], sum(len(site[3]) for site in mine))
                self.assertFalse(result['gameplay_verified'])

    def test_one_bad_site_leaves_the_image_untouched(self):
        boot = self.base / 'derived.bin'
        start = fixture(boot)
        data = bytearray(boot.read_bytes())
        _name, rva, _expected, _replacement = SITES[-1]
        data[start + rva] ^= 0xff
        boot.write_bytes(data)
        profile = effects.validate_source(self.source, list(effects.EFFECTS), METADATA)
        with self.assertRaisesRegex(ValueError, 'signature'):
            effects.apply_prepared(boot, profile)
        self.assertEqual(boot.read_bytes(), data)
        # Applying twice is refused too: the first pass consumed the expected bytes.
        fixture(boot)
        effects.apply_prepared(boot, profile)
        applied = boot.read_bytes()
        with self.assertRaisesRegex(ValueError, 'signature'):
            effects.apply_prepared(boot, profile)
        self.assertEqual(boot.read_bytes(), applied)

    def test_original_path_stale_recipe_and_unknown_effect_are_rejected(self):
        profile = effects.validate_source(self.source, ['film_grain'], METADATA)
        with self.assertRaisesRegex(ValueError, 'derived'):
            effects.apply_prepared(self.source, profile)
        boot = self.base / 'derived.bin'
        fixture(boot)
        before = boot.read_bytes()
        with self.assertRaisesRegex(ValueError, 'verification'):
            effects.apply_prepared(boot, {**profile, 'recipe_sha256': 'stale'})
        self.assertEqual(boot.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, 'Unknown post effect'):
            effects.validate_source(self.source, ['model_detail'], METADATA)
        with self.assertRaisesRegex(ValueError, 'APP_VER'):
            effects.validate_source(self.source, ['film_grain'], {**METADATA, 'APP_VER': '01.02'})

    def test_recipe_identity_ignores_selection_order(self):
        self.assertEqual(effects.recipe_sha256(['film_grain', 'motion_blur']),
                         effects.recipe_sha256(['motion_blur', 'film_grain']))
        self.assertNotEqual(effects.recipe_sha256(['film_grain']), effects.recipe_sha256([]))

    def test_every_edit_keeps_the_instruction_length(self):
        for name, rva, expected, replacement in SITES:
            with self.subTest(effect=name, rva=hex(rva)):
                self.assertEqual(len(expected), len(replacement))
                self.assertNotEqual(expected, replacement)


class PostEffectLauncherTests(unittest.TestCase):
    def test_the_catalogue_offers_the_four_located_effects_on_by_default(self):
        for name in effects.EFFECTS:
            with self.subTest(effect=name):
                field = worker.FIELD_BY_KEY[name]
                self.assertIs(field['default'], True)
                self.assertEqual(field['kind'], 'boolean')
                self.assertTrue(field['available'])
        # The model-detail placebo is gone, not merely disabled.
        self.assertNotIn('model_detail', worker.FIELD_BY_KEY)

    def test_an_effect_turned_off_travels_to_preparation(self):
        values = launcher.load_launch_settings(ROOT / 'out' / 'state', {'game_dir': str(ROOT / 'out' / 'game')})
        self.assertTrue(all(values[name] is True for name in effects.EFFECTS))
        self.assertNotIn('--disable-effects', launcher.backend_command(values))
        values.update(film_grain=False, chromatic_aberration=False)
        command = launcher.backend_command(values)
        self.assertEqual(command[command.index('--disable-effects') + 1], 'film_grain,chromatic_aberration')
        parsed = order1886.argument_parser().parse_args(['--disable-effects', 'film_grain,chromatic_aberration'])
        self.assertEqual(parsed.disable_effects, 'film_grain,chromatic_aberration')

    def test_the_setting_round_trips_through_the_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            app = worker.Worker(state, ROOT)
            values = app.dispatch('settings.set', {'values': {'motion_blur': False}})['settings']
            self.assertIs(values['motion_blur'], False)
            saved = json.loads((state / 'settings.json').read_text(encoding='utf-8'))
            self.assertIs(saved['motion_blur'], False)
            self.assertIs(launcher.load_launch_settings(state)['motion_blur'], False)
            with self.assertRaises(ValueError):
                app.dispatch('settings.set', {'values': {'motion_blur': 0}})


@unittest.skipUnless((GAME / 'eboot.bin').is_file(), 'the extracted CUSA00076 game is not present')
class PostEffectExecutableTests(unittest.TestCase):
    def test_every_site_holds_its_expected_instruction_in_the_real_executable(self):
        data = (GAME / 'eboot.bin').read_bytes()
        if hashlib.sha256(data).hexdigest() != timing.EXPECTED_SELF_SHA256:
            self.skipTest('a different CUSA00076 executable is installed')
        elf = prepare.parse_self(data)[0]
        offset, count = int.from_bytes(elf[0x20:0x28], 'little'), int.from_bytes(elf[0x38:0x3a], 'little')
        for index in range(count):
            header = elf[offset + index * 56:offset + (index + 1) * 56]
            kind, flags = int.from_bytes(header[0:4], 'little'), int.from_bytes(header[4:8], 'little')
            if kind == 1 and flags & 1:  # the executable PT_LOAD segment
                file_offset, address = int.from_bytes(header[8:16], 'little'), int.from_bytes(header[16:24], 'little')
                break
        for name, rva, expected, _replacement in SITES:
            with self.subTest(effect=name, rva=hex(rva)):
                at = file_offset + rva - address
                self.assertEqual(elf[at:at + len(expected)], expected)


if __name__ == '__main__':
    unittest.main()
