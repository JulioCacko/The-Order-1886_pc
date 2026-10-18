"""Read the real native trophy format; never infer unlocks from a launch."""
from pathlib import Path
import tempfile
import unittest
from scripts import order1886_trophy_history as history


class TrophyHistoryTests(unittest.TestCase):
    def test_checksum_and_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / history.RELATIVE_PATH
            path.parent.mkdir(parents=True)
            body = history.HEADER + b"4 1700000000\n12 1700000001\n"
            checksum = 14695981039346656037
            for value in body:
                checksum = ((checksum ^ value) * 1099511628211) & ((1 << 64) - 1)
            path.write_bytes(body + f"END 2 {checksum:x}\n".encode())
            self.assertEqual([item["id"] for item in history.read(root)], [4, 12])
            path.write_bytes(path.read_bytes().replace(b"4 170", b"5 170"))
            with self.assertRaises(ValueError):
                history.read(root)

    def test_missing_history_is_empty_without_creating_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "new"
            self.assertEqual(history.read(root), [])
            self.assertFalse(root.exists())
