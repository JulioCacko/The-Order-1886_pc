import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest

from paths import ROOT

sys.path.insert(0, str(ROOT / 'tools'))
import order1886_graphics_probe as probe


class GraphicsProbeCaptureTests(unittest.TestCase):
    def test_capture_identity_records_dimensions_and_full_file_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'menu.png'
            data = (probe.PNG_SIGNATURE + struct.pack('>I', 13) + b'IHDR'
                    + struct.pack('>II', 2560, 1440) + b'\x08\x06\x00\x00\x00')
            path.write_bytes(data)

            result = probe.capture_identity(path)

        self.assertEqual((result['width'], result['height']), (2560, 1440))
        self.assertEqual(result['sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(result['size_bytes'], len(data))

    def test_capture_identity_rejects_unrecognized_or_zero_sized_images(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.png'
            path.write_bytes(b'not png')
            with self.assertRaisesRegex(ValueError, 'not a complete PNG'):
                probe.capture_identity(path)

            path.write_bytes(probe.PNG_SIGNATURE + struct.pack('>I', 13) + b'IHDR'
                             + struct.pack('>II', 0, 1080))
            with self.assertRaisesRegex(ValueError, 'invalid dimensions'):
                probe.capture_identity(path)

    def test_raw_capture_identity_checks_dimensions_in_name_and_payload_size(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'display_000_1920x1080.raw'
            path.write_bytes(b'\x00' * (1920 * 1080 * 4))
            result = probe.capture_identity(path)
            self.assertEqual((result['width'], result['height']), (1920, 1080))
            self.assertEqual(result['encoding'], 'raw-32-bit')

            path.write_bytes(b'\x00' * 4)
            with self.assertRaisesRegex(ValueError, 'size does not match'):
                probe.capture_identity(path)


if __name__ == '__main__':
    unittest.main()
