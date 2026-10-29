"""Render-size preparation guards; no original game file or GPU is modified."""
import contextlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from paths import ROOT, guest_self

sys.path.insert(0, str(ROOT / 'scripts'))
import order1886_frame_rate as timing
import order1886_resolution as resolution

METADATA = {'TITLE_ID': 'CUSA00076', 'APP_VER': '01.02', 'VERSION': '01.00'}
IMAGE_SIZE = 24512608  # the 01.02 executable's loaded image


def fixture(path):
    start = timing.HEADER.size + 24 + 128 + 32
    with path.open('wb') as stream:
        stream.write(timing.HEADER.pack(b'PS4BOOT2', IMAGE_SIZE, 0xa0, 1, 1, 1, 1))
        stream.write(b'\0' * (24 + 128 + 32))
        stream.seek(start + IMAGE_SIZE - 1)
        stream.write(b'\0')
        for rva, expected in resolution.sites():
            stream.seek(start + rva)
            stream.write(expected)
    return start


class ResolutionPreparationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.source = self.base / 'original eboot.bin'
        self.source.write_bytes(b'original fixture')
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        guest = guest_self(resolution.sites())
        stack.enter_context(patch.object(timing.prepare, 'parse_self', side_effect=lambda data: guest))

    def test_widths_are_checked_and_heights_follow_sixteen_by_nine(self):
        self.assertEqual(resolution.size(3840), (3840, 2160))
        self.assertEqual(resolution.size(2560), (2560, 1440))
        self.assertEqual(resolution.size(1280), (1280, 720))
        for width in (1279, 3841, 7696, 0):
            with self.assertRaises(ValueError):
                resolution.validate_width(width)

    def test_scene_follows_aspect(self):
        self.assertEqual(resolution.scene_size(3840, 'original'), (3840, 1600))
        self.assertEqual(resolution.scene_size(3840, '16:9'), (3840, 2160))
        self.assertEqual(resolution.scene_size(1600, 'original'), (1600, 667))

    def test_original_width_never_touches_missing_derived_image(self):
        profile = resolution.validate_source(self.source, 1920, {})
        result = resolution.apply_prepared(self.base / 'absent.bin', profile)
        self.assertFalse(result['applied'])

    def test_render_target_stack_and_heap_scale_with_the_scene(self):
        sizes = resolution.stack(3840)
        self.assertEqual(sizes['a'], 0x28800000)  # 4x the retail 162 MiB partition
        self.assertEqual(sizes['total'], sizes['a'] + sizes['b'] + sizes['c'])
        self.assertEqual(resolution.stack(1920), {**resolution.STACK, 'a+b': 0xb500000, 'total': 0xfe00000})
        self.assertEqual(resolution.dmem_mb(3840), 5056 + resolution.growth(3840) // (1 << 20))
        resolution.recipe(4192, '16:9')
        with self.assertRaisesRegex(ValueError, 'too large'):
            resolution.recipe(4880, '16:9')

    def test_only_the_recipe_sites_change(self):
        boot = self.base / 'derived.bin'
        start = fixture(boot)
        before = boot.read_bytes()
        result = resolution.apply_prepared(boot, resolution.validate_source(self.source, 3840, METADATA))
        after = boot.read_bytes()
        self.assertTrue(result['applied'])
        self.assertFalse(result['gameplay_verified'])
        self.assertEqual(after[start + resolution.BRANCH_RVA], 0x75)
        changed = {i for i in range(len(before)) if before[i] != after[i]}
        allowed = {start + resolution.BRANCH_RVA}
        for (rva, _), value in zip(resolution.STORES, (3840, 2160, 3840, 2160)):
            self.assertEqual(after[start + rva + 6:start + rva + 10], struct.pack('<I', value))
            allowed |= set(range(start + rva + 6, start + rva + 10))
        for (rva, _), value in zip(resolution.SCENE, (3840, 1600)):
            self.assertEqual(after[start + rva + 1:start + rva + 5], struct.pack('<I', value))
            allowed |= set(range(start + rva + 1, start + rva + 5))
        sizes = resolution.stack(3840)
        for rva, _, at, key in resolution.STACK_SITES:
            self.assertEqual(after[start + rva + at:start + rva + at + 4], struct.pack('<I', sizes[key]))
            allowed |= set(range(start + rva + at, start + rva + at + 4))
        for rva, _, at in resolution.HEAP_SITES:
            self.assertEqual(after[start + rva + at:start + rva + at + 4], struct.pack('<I', resolution.HEAP_SIZE + resolution.growth(3840)))
            allowed |= set(range(start + rva + at, start + rva + at + 4))
        self.assertLessEqual(changed, allowed)

    def test_bad_signature_and_reapplication_preserve_derived_file(self):
        boot = self.base / 'derived.bin'
        start = fixture(boot)
        profile = resolution.validate_source(self.source, 3840, METADATA)
        data = bytearray(boot.read_bytes())
        data[start + resolution.STORES[2][0]] = 0x90
        boot.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'signature'):
            resolution.apply_prepared(boot, profile)
        self.assertEqual(boot.read_bytes(), data)
        fixture(boot)
        resolution.apply_prepared(boot, profile)
        patched = boot.read_bytes()
        with self.assertRaisesRegex(ValueError, 'signature'):
            resolution.apply_prepared(boot, profile)
        self.assertEqual(boot.read_bytes(), patched)


if __name__ == '__main__':
    unittest.main()
