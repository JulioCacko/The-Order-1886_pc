"""Dumps whose eboot.bin already carries the published 60 FPS or 16:9 patch (#3).

Synthetic executables and prepared images only; no game files or GPU process.
"""
from contextlib import contextmanager
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import order1886_display as display
import order1886_frame_rate as timing

METADATA = {'TITLE_ID': 'CUSA00785', 'APP_VER': '01.02', 'VERSION': '01.00'}
IMAGE_SIZE = 0x1600000
HEADER_TABLES = (1, 1, 1)  # sections, relocations, imports: keep the offset formula honest
SITE = timing.INSTRUCTION_RVA
STOCK = timing.EXPECTED_INSTRUCTION
PREPATCHED = timing.PREPATCHED_INSTRUCTION
UNKNOWN = STOCK[:6] + b'\x07\0\0\0'


def stock_sites():
    """Every site any timing or aspect recipe reads, holding the stock 01.02 bytes."""
    sites = {}
    for rate in (60, 90, timing.UNLOCKED):
        sites.update(timing.source_sites(rate))
    sites[display.INSTRUCTION_RVA] = display.EXPECTED_INSTRUCTION
    return sites


def guest_self(sites):
    """What prepare.parse_self returns: one load segment at file offset 0x4000, RVA 0."""
    size = max(rva + len(data) for rva, data in sites.items()) + 16
    elf = bytearray(0x4000 + size)
    for rva, data in sites.items():
        elf[0x4000 + rva:0x4000 + rva + len(data)] = data
    ph = [{'type': 1, 'flags': 5, 'offset': 0x4000, 'vaddr': 0, 'paddr': 0,
           'filesz': size, 'memsz': size, 'align': 0x4000}]
    return elf, None, ph, [], []


class PrepatchedSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.eboot = self.root / 'eboot.bin'
        self.eboot.write_bytes(b'SELF fixture')

    @contextmanager
    def source(self, overrides=None):
        sites = {**stock_sites(), **(overrides or {})}
        with patch.object(timing.prepare, 'read_self', return_value=b'self'), \
                patch.object(timing.prepare, 'parse_self', return_value=guest_self(sites)):
            yield sites

    def boot(self, sites):
        """A PS4BOOT2 image holding the same bytes as the source, like prepare.prepare makes."""
        path = self.root / 'boot.bin'
        ns, nr, ni = HEADER_TABLES
        start = timing.HEADER.size + ns * 24 + ni * 128 + nr * 32
        data = bytearray(start + IMAGE_SIZE)
        timing.HEADER.pack_into(data, 0, b'PS4BOOT2', IMAGE_SIZE, 0xa0, ns, nr, ni, 1)
        for rva, value in sites.items():
            data[start + rva:start + rva + len(value)] = value
        path.write_bytes(data)
        return path, start

    def at(self, path, start, rva, size=10):
        return path.read_bytes()[start + rva:start + rva + size]

    def prepare(self, rate, overrides=None):
        with self.source(overrides) as sites:
            profile = timing.validate_source(self.eboot, rate, METADATA)
        path, start = self.boot(sites)
        return profile, timing.apply_prepared(path, profile), path, start

    def test_stock_executable_unchanged_behaviour(self):
        profile, result, path, start = self.prepare(60)
        self.assertEqual(profile['source_prepatched'], [])
        self.assertEqual((result['applied'], result['changed_bytes']), (True, 1))
        self.assertEqual(self.at(path, start, SITE), PREPATCHED)
        profile, result, path, start = self.prepare(30)
        self.assertNotIn('source_prepatched', profile)
        self.assertFalse(result['applied'])
        self.assertEqual(self.at(path, start, SITE), STOCK)

    def test_60_fps_accepts_a_prepatched_executable_without_writing(self):
        with self.source({SITE: PREPATCHED}) as sites:
            profile = timing.validate_source(self.eboot, 60, METADATA)
        self.assertEqual(profile['source_prepatched'], [hex(SITE)])
        path, start = self.boot(sites)
        before = path.read_bytes()
        result = timing.apply_prepared(path, profile)
        self.assertEqual((result['applied'], result['changed_bytes']), (True, 0))
        self.assertEqual(path.read_bytes(), before)

    def test_30_fps_restores_the_native_interval(self):
        with self.source({SITE: PREPATCHED}) as sites:
            profile = timing.validate_source(self.eboot, 30, METADATA)
        self.assertEqual(profile['source_prepatched'], [hex(SITE)])
        path, start = self.boot(sites)
        result = timing.apply_prepared(path, profile)
        self.assertEqual((result['applied'], result['changed_bytes']), (True, 1))
        self.assertEqual(self.at(path, start, SITE), STOCK)

    def test_90_and_unlocked_write_their_interval_over_the_published_one(self):
        for rate, interval in ((90, 1), (timing.UNLOCKED, 0)):
            with self.subTest(rate=rate), self.source({SITE: PREPATCHED}) as sites:
                profile = timing.validate_source(self.eboot, rate, METADATA)
                path, start = self.boot(sites)
                result = timing.apply_prepared(path, profile)
                self.assertTrue(result['applied'])
                self.assertEqual(self.at(path, start, SITE), timing.interval_write(SITE, interval))
                for rva, _, replacement in timing.edits(rate):
                    self.assertEqual(self.at(path, start, rva, len(replacement)), replacement)

    def test_other_bytes_are_still_refused(self):
        for rate in (60, 90, timing.UNLOCKED):
            with self.subTest(rate=rate), self.source({SITE: UNKNOWN}), \
                    self.assertRaisesRegex(ValueError, 'does not match this executable'):
                timing.validate_source(self.eboot, rate, METADATA)
        with self.source({SITE: UNKNOWN}):
            self.assertNotIn('source_prepatched', timing.validate_source(self.eboot, 30, METADATA))

    def test_prepared_image_must_still_match_the_profile(self):
        with self.source({SITE: PREPATCHED}) as sites:
            profile = timing.validate_source(self.eboot, 30, METADATA)
        path, _ = self.boot({**sites, SITE: UNKNOWN})
        with self.assertRaisesRegex(ValueError, 'signature mismatch'):
            timing.apply_prepared(path, profile)

    def test_aspect_prepatched_executable(self):
        site = display.INSTRUCTION_RVA
        with self.source({site: display.REPLACEMENT_INSTRUCTION}) as sites:
            wide = display.validate_source(self.eboot, '16:9', METADATA)
            original = display.validate_source(self.eboot, 'original', METADATA)
        self.assertEqual(wide['source_prepatched'], [hex(site)])
        path, start = self.boot(sites)
        result = display.apply_prepared(path, wide)
        self.assertEqual((result['applied'], result['changed_bytes']), (True, 0))
        self.assertEqual(self.at(path, start, site), display.REPLACEMENT_INSTRUCTION)
        path, start = self.boot(sites)
        result = display.apply_prepared(path, original)
        self.assertTrue(result['applied'])
        self.assertEqual(self.at(path, start, site), display.EXPECTED_INSTRUCTION)

    def test_aspect_stock_executable_unchanged_behaviour(self):
        site = display.INSTRUCTION_RVA
        with self.source() as sites:
            wide = display.validate_source(self.eboot, '16:9', METADATA)
            original = display.validate_source(self.eboot, 'original', METADATA)
        self.assertNotIn('source_prepatched', original)
        path, start = self.boot(sites)
        self.assertEqual(display.apply_prepared(path, wide)['changed_bytes'], 4)
        self.assertEqual(self.at(path, start, site), display.REPLACEMENT_INSTRUCTION)
        self.assertFalse(display.apply_prepared(path, original)['applied'])


if __name__ == '__main__':
    unittest.main()
