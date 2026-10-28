"""Full-screen preparation guards; no original game file or GPU is modified."""
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from paths import ROOT, guest_self

sys.path.insert(0, str(ROOT / 'scripts'))
import order1886_frame_rate as timing
import order1886_display as display

METADATA = {'TITLE_ID': 'CUSA00076', 'APP_VER': '01.02', 'VERSION': '01.00'}
SIGNATURE = bytes.fromhex('c78518fcffff9a991940')
SITE = 0x44ce86
IMAGE_SIZE = 24512608  # the 01.02 executable's loaded image


def fixture(path):
    start = timing.HEADER.size + 24 + 128 + 32
    with path.open('wb') as stream:
        stream.write(timing.HEADER.pack(b'PS4BOOT2', IMAGE_SIZE, 0xa0, 1, 1, 1, 1))
        stream.write(b'\0' * (24 + 128 + 32))
        stream.seek(start + IMAGE_SIZE - 1)
        stream.write(b'\0')
        stream.seek(start + SITE)
        stream.write(SIGNATURE)
    return start + SITE


class DisplayPreparationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.source = self.base / 'original eboot.bin'
        self.source.write_bytes(b'original fixture')
        self.guest = guest_self([(SITE, SIGNATURE)])
        self.stack = __import__('contextlib').ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(timing.prepare, 'parse_self', side_effect=lambda data: self.guest))

    def test_original_profile_never_touches_missing_derived_image(self):
        profile = display.validate_source(self.source, 'original', {})
        result = display.apply_prepared(self.base / 'absent.bin', profile)
        self.assertFalse(result['applied'])
        self.assertEqual(result['aspect_ratio'], 'original')

    def test_fullscreen_changes_only_verified_float_immediate(self):
        boot = self.base / 'derived.bin'
        offset = fixture(boot)
        before = boot.read_bytes()
        original = self.source.read_bytes()
        profile = display.validate_source(self.source, '16:9', METADATA)
        result = display.apply_prepared(boot, profile)
        after = boot.read_bytes()
        self.assertEqual(after[:offset + 6], before[:offset + 6])
        self.assertEqual(after[offset + 10:], before[offset + 10:])
        self.assertEqual(after[offset + 6:offset + 10], struct.pack('<I', 0x3fe38e39))
        self.assertEqual(self.source.read_bytes(), original)
        self.assertTrue(result['applied'])
        self.assertEqual(result['changed_bytes'], 4)
        self.assertEqual(result['public_patch_address'], '0x0084ce8c')
        self.assertFalse(result['gameplay_verified'])

    def test_bad_signature_and_reapplication_preserve_derived_file(self):
        boot = self.base / 'derived.bin'
        offset = fixture(boot)
        profile = display.validate_source(self.source, '16:9', METADATA)
        data = bytearray(boot.read_bytes())
        data[offset] = 0x90
        boot.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'signature'):
            display.apply_prepared(boot, profile)
        self.assertEqual(boot.read_bytes(), data)
        fixture(boot)
        display.apply_prepared(boot, profile)
        before = boot.read_bytes()
        with self.assertRaisesRegex(ValueError, 'signature'):
            display.apply_prepared(boot, profile)
        self.assertEqual(boot.read_bytes(), before)

    def test_original_path_source_and_stale_recipe_are_rejected(self):
        profile = display.validate_source(self.source, '16:9', METADATA)
        with self.assertRaisesRegex(ValueError, 'derived'):
            display.apply_prepared(self.source, profile)
        boot = self.base / 'derived.bin'
        fixture(boot)
        before = boot.read_bytes()
        with self.assertRaisesRegex(ValueError, 'verification'):
            display.apply_prepared(boot, {**profile, 'recipe_sha256': 'stale'})
        self.assertEqual(boot.read_bytes(), before)

    def test_unsupported_source_metadata_and_aspect_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'aspect'):
            display.validate_source(self.source, 'stretch', METADATA)
        with self.assertRaisesRegex(ValueError, 'selected game is CUSA00207'):
            display.validate_source(self.source, '16:9', {**METADATA, 'TITLE_ID': 'CUSA00207'})
        for edition in timing.editions.TITLE_IDS:
            with self.subTest(edition=edition):
                self.assertTrue(display.validate_source(self.source, '16:9', {**METADATA, 'TITLE_ID': edition})['source_verified'])
        self.guest = guest_self([(SITE, b'\x90' * len(SIGNATURE))])
        with self.assertRaisesRegex(ValueError, 'does not match this executable at RVA 0x44ce86') as caught:
            display.validate_source(self.source, '16:9', METADATA)
        self.assertIn('Original cinematic aspect', str(caught.exception))
        self.assertNotIn('Select 30 FPS', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
