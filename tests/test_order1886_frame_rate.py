"""Timing recipe guards use synthetic prepared images, never a game/GPU process."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
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
    def test_supplied_xml_unlock_matches_guarded_recipe_without_other_patches(self):
        source = ROOT / 'patches/TheOrder1886-Orbis.xml'
        content = source.read_bytes().replace(b'\r\n', b'\n')
        self.assertEqual(hashlib.sha256(content).hexdigest(), timing.PUBLIC_PATCH_XML_SHA256)
        document = ET.fromstring(content)
        self.assertIn(timing.EXPECTED_METADATA['TITLE_ID'], [node.text for node in document.findall('./TitleID/ID')])
        unlock = next(node for node in document.findall('Metadata') if node.get('Name') == '60 FPS Unlock')
        lines = unlock.findall('./PatchList/Line')
        self.assertEqual(len(lines), 1)
        self.assertEqual(unlock.get('AppVer'), '01.02')
        self.assertEqual(unlock.get('AppElf'), 'eboot.bin')
        self.assertEqual(unlock.get('Author'), 'illusion')
        self.assertEqual(lines[0].get('Type'), 'byte')
        self.assertEqual(int(lines[0].get('Value'), 16), 1)
        profile = timing.recipe(60)
        self.assertEqual(int(lines[0].get('Address'), 16),
                         timing.PUBLIC_IMAGE_BASE + timing.INSTRUCTION_RVA + 6)
        self.assertEqual(profile['public_patch_xml_sha256_lf'], timing.PUBLIC_PATCH_XML_SHA256)
        self.assertEqual(profile['public_patch_entry'], '60 FPS Unlock')
        self.assertEqual(profile['public_patch_address'], lines[0].get('Address'))
        self.assertNotEqual(unlock.get('AppVer'), timing.EXPECTED_METADATA['APP_VER'])

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
        with self.assertRaisesRegex(ValueError, '30, 60 or 90'):
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


def write_high_rate_fixture(path):
    """Every 90/unlocked site as the verified executable has it, in a 60-site boot fixture."""
    image_offset = write_boot_fixture(path) - SITE_RVA
    with Path(path).open('r+b') as stream:
        for rva, expected, _ in timing.edits(timing.UNLOCKED) + timing.edits(90):
            stream.seek(image_offset + rva)
            stream.write(expected)
    return image_offset


@contextmanager
def verified_high_rate_source(source, rate):
    with verified_fixture_source(source):
        yield timing.validate_source(source, rate, METADATA)


class HighRateRecipeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.source = self.base / 'original eboot.bin'
        self.source.write_bytes(b'owned original fixture')

    def test_sites_encode_the_interval_global_and_the_engine_constants(self):
        for rva, expected, _ in timing.edits(timing.UNLOCKED):
            if rva != timing.SYNC_ARGUMENTS_RVA:  # mov dword [RIP+disp32], imm32
                self.assertEqual(rva + 10 + struct.unpack_from('<i', expected, 2)[0], timing.TARGET_GLOBAL_RVA)
        self.assertEqual(timing.interval_write(SITE_RVA, 2), SIGNATURE)
        pacer = timing.pacer_instruction(timing.PACER_MICROSECONDS)
        self.assertEqual(timing.PACER_RVA + 11 + struct.unpack_from('<i', pacer, 3)[0], timing.TARGET_GLOBAL_RVA)
        self.assertEqual(pacer.hex(), '446935adb1d8001a410000')

    def test_ninety_sets_interval_one_everywhere_and_shortens_the_pacer(self):
        changes = {rva: new for rva, _, new in timing.edits(90)}
        self.assertEqual(changes[timing.SYNC_ARGUMENTS_RVA], b'-frontend -syncinterval 1\0')
        self.assertEqual(sorted(changes), sorted([timing.SYNC_ARGUMENTS_RVA, 0x4507be, 0x7658dd, 0x765b6e,
                                                  timing.PACER_RVA]))
        self.assertEqual(struct.unpack_from('<I', changes[timing.PACER_RVA], 7)[0], 11111)
        self.assertTrue(all(struct.unpack_from('<I', new, 6)[0] == 1 for rva, new in changes.items()
                            if rva in timing.INTERVAL_WRITES))

    def test_unlocked_sets_interval_zero_at_every_write_and_keeps_the_pacer(self):
        changes = {rva: new for rva, _, new in timing.edits(timing.UNLOCKED)}
        self.assertEqual(changes[timing.SYNC_ARGUMENTS_RVA], b'-frontend -syncinterval 0\0')
        self.assertEqual(sorted(changes), sorted([timing.SYNC_ARGUMENTS_RVA, *timing.INTERVAL_WRITES]))
        self.assertTrue(all(new[6:] == b'\0' * 4 for rva, new in changes.items() if rva in timing.INTERVAL_WRITES))

    def test_apply_changes_only_the_recipe_bytes(self):
        for rate in (90, timing.UNLOCKED):
            with self.subTest(rate=rate):
                boot = self.base / f'derived {rate}.bin'
                image_offset = write_high_rate_fixture(boot)
                before = bytearray(boot.read_bytes())
                with verified_high_rate_source(self.source, rate) as profile:
                    result = timing.apply_prepared(boot, profile)
                after = boot.read_bytes()
                for rva, _, new in timing.edits(rate):
                    before[image_offset + rva:image_offset + rva + len(new)] = new
                self.assertEqual(after, bytes(before))
                self.assertTrue(result['applied'])
                self.assertEqual(result['engine_fps'], rate)
                self.assertIn('Chapter 6 and 9', result['warning'])
                self.assertEqual(self.source.read_bytes(), b'owned original fixture')

    def test_one_mismatched_site_writes_nothing_and_reapplication_is_rejected(self):
        boot = self.base / 'derived boot.bin'
        image_offset = write_high_rate_fixture(boot)
        with boot.open('r+b') as stream:
            stream.seek(image_offset + timing.PACER_RVA)
            stream.write(b'\x90')
        before = boot.read_bytes()
        with verified_high_rate_source(self.source, 90) as profile:
            with self.assertRaisesRegex(ValueError, 'signature mismatch at RVA 0x835b9c'):
                timing.apply_prepared(boot, profile)
            self.assertEqual(boot.read_bytes(), before)
            write_high_rate_fixture(boot)
            timing.apply_prepared(boot, profile)
            patched = boot.read_bytes()
            with self.assertRaisesRegex(ValueError, 'signature mismatch'):
                timing.apply_prepared(boot, profile)
            self.assertEqual(boot.read_bytes(), patched)

    def test_stale_recipe_hash_is_refused(self):
        boot = self.base / 'derived boot.bin'
        write_high_rate_fixture(boot)
        before = boot.read_bytes()
        with verified_high_rate_source(self.source, timing.UNLOCKED) as profile:
            with self.assertRaisesRegex(ValueError, 'stale'):
                timing.apply_prepared(boot, {**profile, 'recipe_sha256': timing.recipe_sha256(90)})
        self.assertEqual(boot.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
