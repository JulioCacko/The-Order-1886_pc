"""Timing recipe guards use synthetic prepared images, never a game/GPU process."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from paths import ROOT

sys.path.insert(0, str(ROOT / 'scripts'))
import order1886_frame_rate as timing

METADATA = {'TITLE_ID': 'CUSA00076', 'APP_VER': '01.00', 'VERSION': '01.03'}
SITE_RVA = 0x4507be
IMAGE_SIZE = 24512608
SIGNATURE = bytes.fromhex('c7058c05170102000000')


def write_boot_fixture(path):
    """Use nonempty tables so a wrong image-offset formula cannot accidentally pass."""
    image_offset = 56 + 24 + 128 + 32
    with Path(path).open('wb') as stream:
        stream.write(struct.pack('<8s6Q', b'PS4BOOT2', IMAGE_SIZE, 0xa0, 1, 1, 1, 1))
        stream.write(struct.pack('<3Q', 0, IMAGE_SIZE, 5))
        stream.write(b'fixture#library'.ljust(128, b'\0'))
        stream.write(b'\0' * 32)
        stream.seek(image_offset + IMAGE_SIZE - 1)
        stream.write(b'\0')
        stream.seek(image_offset + SITE_RVA)
        stream.write(SIGNATURE)
    return image_offset + SITE_RVA


@contextmanager
def verified_fixture_source(source):
    elf = bytearray(b'fixture reconstructed ELF')
    with patch.object(timing, 'EXPECTED_SELF_SHA256', hashlib.sha256(source.read_bytes()).hexdigest()), \
            patch.object(timing, 'EXPECTED_ELF_SHA256', hashlib.sha256(elf).hexdigest()), \
            patch.object(timing.prepare, 'parse_self', return_value=(elf, None, None, None, None)):
        yield timing.validate_source(source, 60, METADATA)


class FrameRateRecipeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.source = self.base / 'original eboot.bin'
        self.source.write_bytes(b'owned original fixture')

    def test_native_30_does_not_require_the_60_hash_or_touch_a_boot_file(self):
        profile = timing.validate_source(self.source, 30, METADATA)
        absent = self.base / 'not-created.bin'
        result = timing.apply_prepared(absent, profile)
        self.assertFalse(result['applied'])
        self.assertEqual(result['engine_fps'], 30)
        self.assertFalse(absent.exists())

    def test_unsupported_rate_and_self_hash_are_explicit_errors(self):
        before = self.source.read_bytes()
        with self.assertRaisesRegex(ValueError, '30 or 60'):
            timing.validate_source(self.source, 120, METADATA)
        with self.assertRaisesRegex(ValueError, 'SELF SHA256'):
            timing.validate_source(self.source, 60, METADATA)
        self.assertEqual(self.source.read_bytes(), before)

    def test_reconstructed_elf_and_metadata_must_also_match(self):
        with patch.object(timing, 'EXPECTED_SELF_SHA256', hashlib.sha256(self.source.read_bytes()).hexdigest()), \
                patch.object(timing.prepare, 'parse_self', return_value=(b'wrong ELF', None, None, None, None)):
            with self.assertRaisesRegex(ValueError, 'ELF SHA256'):
                timing.validate_source(self.source, 60, METADATA)
        with verified_fixture_source(self.source):
            with self.assertRaisesRegex(ValueError, 'APP_VER'):
                timing.validate_source(self.source, 60, {**METADATA, 'APP_VER': '01.02'})

    def test_only_the_immediate_changes_and_original_source_is_untouched(self):
        boot = self.base / 'derived boot.bin'
        offset = write_boot_fixture(boot)
        original_source = self.source.read_bytes()
        before = boot.read_bytes()
        with verified_fixture_source(self.source) as profile:
            result = timing.apply_prepared(boot, profile)
        after = boot.read_bytes()
        self.assertEqual(before[:offset + 6], after[:offset + 6])
        self.assertEqual(before[offset + 7:], after[offset + 7:])
        self.assertEqual(before[offset + 6], 2)
        self.assertEqual(after[offset + 6], 1)
        self.assertEqual(self.source.read_bytes(), original_source)
        self.assertTrue(result['applied'])
        self.assertEqual(result['target_global_rva'], '0x15c0d54')
        self.assertEqual(result['changed_bytes'], 1)
        self.assertIn('Chapters 6 and 9', result['warning'])

    def test_signature_mismatch_never_writes_and_reapplication_is_rejected(self):
        boot = self.base / 'derived boot.bin'
        offset = write_boot_fixture(boot)
        with boot.open('r+b') as stream:
            stream.seek(offset)
            stream.write(b'\x90')
        before = hashlib.sha256(boot.read_bytes()).hexdigest()
        with verified_fixture_source(self.source) as profile:
            with self.assertRaisesRegex(ValueError, 'instruction signature'):
                timing.apply_prepared(boot, profile)
            self.assertEqual(hashlib.sha256(boot.read_bytes()).hexdigest(), before)
            write_boot_fixture(boot)
            timing.apply_prepared(boot, profile)
            patched = hashlib.sha256(boot.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, 'instruction signature'):
                timing.apply_prepared(boot, profile)
            self.assertEqual(hashlib.sha256(boot.read_bytes()).hexdigest(), patched)

    def test_malformed_header_and_wrong_rip_target_never_write(self):
        boot = self.base / 'derived boot.bin'
        boot.write_bytes(b'PS4BOOT2')
        before = boot.read_bytes()
        with verified_fixture_source(self.source) as profile:
            with self.assertRaisesRegex(ValueError, 'header'):
                timing.apply_prepared(boot, profile)
            self.assertEqual(boot.read_bytes(), before)
            write_boot_fixture(boot)
            before_hash = hashlib.sha256(boot.read_bytes()).hexdigest()
            with patch.object(timing, 'TARGET_GLOBAL_RVA', 0x15c0d58):
                with self.assertRaisesRegex(ValueError, 'RIP target'):
                    timing.apply_prepared(boot, profile)
            self.assertEqual(hashlib.sha256(boot.read_bytes()).hexdigest(), before_hash)


if __name__ == '__main__':
    unittest.main()
