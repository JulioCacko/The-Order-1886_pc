import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import order1886_ui_extract as ui  # noqa: E402


def tag(code, data):
    if len(data) < 63:
        return struct.pack('<H', code << 6 | len(data)) + data
    return struct.pack('<HI', code << 6 | 63, len(data)) + data


def rect(xmin, xmax, ymin, ymax):
    n = 17  # signed: 1920 px = 38400 twips needs 17 bits
    bits = format(n, '05b') + ''.join(format(v & 0x1ffff, '017b') for v in (xmin, xmax, ymin, ymax))
    bits += '0' * (-len(bits) % 8)
    return bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8))


NO_MATRIX = b'\x00'  # no scale, no rotate, 0-bit translate
GLYPH_CLASS = 'rad.widgets.buttons.smallscale.ButtonIconSmallNormalCross'


def movie():
    # 2x1 premultiplied ARGB: opaque red, then half-transparent red stored as R=64.
    pixels = bytes([255, 255, 0, 0, 128, 64, 0, 0])
    bitmap = tag(36, struct.pack('<HBHH', 1, 5, 2, 1) + zlib.compress(pixels))
    shape = tag(2, struct.pack('<H', 2) + rect(0, 40, 0, 20) + b'\x01\x41' + struct.pack('<H', 1)
                + NO_MATRIX + b'\x00\x00')
    sprite_tags = tag(26, b'\x06' + struct.pack('<HH', 1, 2) + NO_MATRIX) + tag(1, b'') + tag(0, b'')
    sprite = tag(39, struct.pack('<HH', 3, 1) + sprite_tags)
    symbols = tag(76, struct.pack('<HH', 1, 3) + GLYPH_CLASS.encode() + b'\0')
    body = rect(0, 1920 * 20, 0, 800 * 20) + b'\x00\x1e' + struct.pack('<H', 1)
    body += bitmap + shape + sprite + symbols + tag(1, b'') + tag(0, b'')
    return b'CWS\x09' + struct.pack('<I', len(body) + 8) + zlib.compress(body)


class UiExtractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_finds_movie_behind_length_prefix_and_ignores_false_signatures(self):
        swf = movie()
        payload = b'CWS\x09junkjunk' + struct.pack('<I', len(swf)) + swf
        self.assertEqual(ui.find_swfs(payload), [16])

    def test_extracts_bitmap_symbol_owner_glyph_and_stage(self):
        result = ui.extract_movie(movie(), self.root / 'movie')
        self.assertEqual(result['stage'], [0, 1920, 0, 800])
        [bitmap] = result['bitmaps']
        self.assertEqual((bitmap['id'], bitmap['width'], bitmap['height']), (1, 2, 1))
        self.assertEqual(bitmap['symbols'], [GLYPH_CLASS])
        self.assertEqual(bitmap['glyph'], 'cross')
        [symbol] = result['symbols']
        self.assertEqual((symbol['id'], symbol['bitmaps'], symbol['glyph']), (3, [1], 'cross'))
        self.assertEqual(symbol['placements'][0]['character'], 2)
        from PIL import Image
        image = Image.open(self.root / 'movie' / bitmap['png'])
        self.assertEqual(image.getpixel((0, 0)), (255, 0, 0, 255))
        red, _, _, alpha = image.getpixel((1, 0))
        self.assertEqual(alpha, 128)
        self.assertAlmostEqual(red, 127, delta=1)  # premultiplied 64 / 0.5
        swf = (self.root / 'movie' / 'movie.swf').read_bytes()
        self.assertEqual(swf[:3], b'FWS')
        json.dumps(result)  # the manifest entry must serialise

    def test_compress_chunk_table(self):
        chunk = b'x' * 5
        blob = b'COMPRESS' + struct.pack('<QQ', ui.CHUNK + 7, 0)
        blob += struct.pack('<QQ', 0, len(chunk)) + chunk + struct.pack('<QQ', ui.CHUNK, 3) + b'abc'
        raw, chunks = ui.container_chunks(blob)
        self.assertEqual(raw, ui.CHUNK + 7)
        self.assertEqual([(c[2], c[3]) for c in chunks], [(0, ui.CHUNK), (ui.CHUNK, 7)])
        single = b'COMPRESS' + struct.pack('<QQ', 100, 4) + b'\x47abc'
        self.assertEqual(ui.container_chunks(single), (100, [(24, 4, 0, 100)]))

    def test_stored_container_layout(self):
        raw = bytes(range(256)) * (ui.CHUNK // 128)  # two full chunks
        blob = ui.stored_container(raw + b'tail')
        size, chunks = ui.container_chunks(blob)
        self.assertEqual(size, len(raw) + 4)
        self.assertEqual(struct.unpack_from('<Q', blob, 16)[0], len(blob))  # chunked: file size
        self.assertEqual(b''.join(blob[p + 1:p + n] for p, n, _, _ in chunks), raw + b'tail')
        self.assertTrue(all(blob[p] == 0 for p, _, _, _ in chunks))  # stored-block header
        single = ui.stored_container(b'abc', chunked=False)
        self.assertEqual(ui.container_chunks(single), (3, [(24, 4, 0, 3)]))

    def test_raw_resources_pass_through_without_decoder(self):
        self.assertEqual(ui.payload(b'plain', None), (b'plain', 'raw'))
        with self.assertRaises(ValueError):
            ui.payload(b'COMPRESS' + bytes(16), None)

    def test_output_must_stay_outside_repository_and_game(self):
        game = self.root / 'game'
        with self.assertRaises(SystemExit):
            ui.check_output(ROOT / 'out' / 'ui', game)
        with self.assertRaises(SystemExit):
            ui.check_output(game / 'ui', game)
        self.assertEqual(ui.check_output(self.root / 'ui', game), (self.root / 'ui').resolve())


if __name__ == '__main__':
    unittest.main()
