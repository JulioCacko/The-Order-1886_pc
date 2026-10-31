from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import order1886_glyph_mod as glyphs  # noqa: E402
import order1886_ui_extract as ui  # noqa: E402
from test_order1886_ui_extract import movie  # noqa: E402


def info(**overrides):
    base = dict(box=[0, 0, 64, 64], area=0.9, fill=0.8, detail=40, dark=0.3, inverted=False,
                soft=False, flat=False)
    return {**base, **overrides}


class GlyphModTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_rebuild_replaces_bitmap_keeping_id_and_size(self):
        from PIL import Image
        new = Image.new('RGBA', (2, 1), (0, 255, 0, 255))
        rebuilt = glyphs.rebuild_swf(movie(), {1: glyphs.lossless2(1, new)})
        parsed = ui.parse_swf(rebuilt)
        bitmap = parsed['bitmaps'][1]
        self.assertEqual((bitmap['tag'], bitmap['width'], bitmap['height']), ('DefineBitsLossless2', 2, 1))
        self.assertEqual(ui.decode_bitmap(bitmap).getpixel((1, 0)), (0, 255, 0, 255))
        self.assertEqual(ui.bitmaps_under(parsed, 3), {1})  # symbol still draws it

    def test_place_respects_slots(self):
        swf = movie()
        payload = b'head' + struct.pack('<I', len(swf) + 32) + swf + bytes(32) + b'tail'
        smaller = swf[:-4]
        placed = glyphs.place(payload, 8, smaller)
        self.assertEqual(len(placed), len(payload))
        self.assertTrue(placed.endswith(bytes(36) + b'tail'))
        with self.assertRaisesRegex(ValueError, 'slot'):
            glyphs.place(payload, 8, swf + bytes(64))
        alone = struct.pack('<I', len(swf)) + swf
        self.assertEqual(glyphs.place(alone, 4, swf + b'grow'), struct.pack('<I', len(swf) + 4) + swf + b'grow')

    def test_repack_keeps_unchanged_chunks(self):
        original = bytes(range(256)) * (ui.CHUNK // 128)  # two chunks
        blob = b'COMPRESS' + struct.pack('<QQ', len(original), 0)
        coded = [b'oodle-0', b'oodle-1']  # stand-ins for the original compressed chunks
        for i, c in enumerate(coded):
            blob += struct.pack('<QQ', i * ui.CHUNK, len(c)) + c
        changed = original[:ui.CHUNK] + b'X' + original[ui.CHUNK + 1:]
        out = glyphs.repack(blob, original, changed)
        _, chunks = ui.container_chunks(out)
        self.assertEqual(out[chunks[0][0]:chunks[0][0] + chunks[0][1]], b'oodle-0')
        p, n, _, _ = chunks[1]
        self.assertEqual(out[p:p + n], b'\x00' + changed[ui.CHUNK:])  # stored block
        self.assertEqual(struct.unpack_from('<Q', out, 16)[0], len(out))
        self.assertEqual(glyphs.repack(b'raw resource', b'', b'new'), b'new')

    def test_roles(self):
        self.assertEqual(glyphs.suggest_role(info(), True, 'cross'), 'face')
        self.assertEqual(glyphs.suggest_role(info(flat=True), True, 'l1'), 'keep')  # black mask
        self.assertEqual(glyphs.suggest_role(info(area=0.1, fill=0.3), False, 'r3'), 'label')
        self.assertEqual(glyphs.suggest_role(info(area=0.4, fill=0.15, detail=0, flat=True), False,
                                             'circle'), 'label')  # a lone (black) O ring
        self.assertEqual(glyphs.suggest_role(info(fill=0.05, detail=0, dark=0), False, 'l3'), 'keep')

    def test_keyboard_labels_follow_bindings(self):
        labels = glyphs.labels_for('keyboard', {'cross': 'Q', 'circle': 'Left Shift'})
        self.assertEqual((labels['cross'], labels['circle'], labels['r2']), ('Q', 'SHIFT', 'LMB'))
        self.assertEqual(glyphs.labels_for('xbox')['triangle'], 'Y')

    def test_art_precedence(self):
        from PIL import Image
        original = Image.new('RGBA', (32, 32), (255, 255, 255, 255))
        entry = dict(info(box=[0, 0, 32, 32]), key='MenuApp-4-104', glyph='cross', role='face')
        labels = glyphs.labels_for('xbox')
        drawn = glyphs.replacement(entry, original, 'xbox', labels, None)
        self.assertEqual(drawn.size, (32, 32))
        art = self.root / 'art'
        (art / 'xbox' / 'bitmaps').mkdir(parents=True)
        Image.new('RGBA', (8, 8), (255, 0, 0, 255)).save(art / 'xbox' / 'cross.png')
        generic = glyphs.replacement(entry, original, 'xbox', labels, art)
        self.assertEqual(generic.getpixel((16, 16))[:3], (255, 0, 0))
        Image.new('RGBA', (64, 64), (0, 0, 255, 255)).save(art / 'xbox' / 'bitmaps' / 'MenuApp-4-104.png')
        exact = glyphs.replacement(entry, original, 'xbox', labels, art)
        self.assertEqual((exact.size, exact.getpixel((0, 0))), ((32, 32), (0, 0, 255, 255)))


if __name__ == '__main__':
    unittest.main()
