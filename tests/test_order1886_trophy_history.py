"""Read the real native trophy format; never infer unlocks from a launch."""
from pathlib import Path
import base64
import hashlib
import struct
import tempfile
import unittest
from scripts import order1886_trophy_history as history


def trophy_archive(entries):
    """TRP v3 layout from shadPS4's TrpHeader/TrpEntry, without game assets."""
    offset = 96 + len(entries) * 64
    table, payload = bytearray(), bytearray()
    for name, data, flag in entries:
        table += struct.pack('>32sQQI12x', name.encode(), offset, len(data), flag)
        payload += data
        offset += len(data)
    header = struct.pack('>IIQIII20sI44x', 0xdca24d00, 3, offset, len(entries), 64, 0, bytes(20), 0)
    archive = bytearray(header + table + payload)
    archive[28:48] = hashlib.sha1(archive).digest()
    return archive


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9WQAAAAASUVORK5CYII=')


class TrophyHistoryTests(unittest.TestCase):
    def test_catalog_rejects_corruption_unsafe_entries_and_oversized_images(self):
        valid = trophy_archive([('TROP000.PNG', PNG, 0)])
        bad_digest = bytearray(valid)
        bad_digest[-1] ^= 1
        bad_offset = bytearray(valid)
        struct.pack_into('>Q', bad_offset, 128, len(valid) + 1)
        bad_offset[28:48] = bytes(20)
        bad_offset[28:48] = hashlib.sha1(bad_offset).digest()
        huge_png = bytearray(PNG)
        struct.pack_into('>I', huge_png, 16, 100000)
        cases = [b'', bad_digest, bad_offset,
                 trophy_archive([('../TROP000.PNG', PNG, 0)]),
                 trophy_archive([('TROP000.PNG', PNG, 0), ('TROP000.PNG', PNG, 0)]),
                 trophy_archive([('TROP000.PNG', huge_png, 0)])]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'sce_sys/trophy/trophy00.trp'
            path.parent.mkdir(parents=True)
            for data in cases:
                with self.subTest(data_length=len(data)):
                    path.write_bytes(data)
                    with self.assertRaises(ValueError):
                        history.catalog(root)
                    self.assertEqual(path.read_bytes(), data)
            path.write_bytes(trophy_archive([(f'TROP{i:03}.PNG', PNG + bytes(100000), 0) for i in range(9)]))
            with self.assertRaisesRegex(ValueError, 'response limit'):
                history.catalog(root, set(range(9)))

    def test_installed_artwork_catalog_preserves_sources_and_locked_spoilers(self):
        with tempfile.TemporaryDirectory() as directory:
            game = Path(directory)
            source = game / 'sce_sys/trophy/trophy00.trp'
            source.parent.mkdir(parents=True)
            original = trophy_archive([('TROP000.PNG', PNG, 0), ('TROP001.PNG', PNG, 0),
                                       ('TROP.ESFM', b'encrypted names', 3)])
            source.write_bytes(original)
            catalog = history.catalog(game, {1})
            self.assertEqual([item['id'] for item in catalog], [0, 1])
            self.assertEqual(catalog[0]['icon'], '')
            self.assertEqual(catalog[1]['icon'], 'data:image/png;base64,' + base64.b64encode(PNG).decode())
            self.assertEqual(source.read_bytes(), original)

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


class TrophyTextTests(unittest.TestCase):
    """shadPS4's ESFM decryption, against an archive encrypted here with a made-up key."""

    def archive_with_text(self, key, documents):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from scripts import order1886_trophy_text as text
        entries = [('TROP000.PNG', PNG, 0)]
        for name, document in documents.items():
            iv = bytes(range(16, 32))
            padded = document + bytes(-len(document) % 16)
            encryptor = Cipher(algorithms.AES(text.entry_key(key)), modes.CBC(iv)).encryptor()
            entries.append((name, iv + encryptor.update(padded) + encryptor.finalize(), 3))
        return trophy_archive(entries)

    def test_names_come_from_the_players_language_and_a_wrong_key_is_refused(self):
        key = bytes(range(1, 17))
        english = (b'<?xml version="1.0" encoding="UTF-8"?><trophyconf><trophy id="000" hidden="no" '
                   b'ttype="B"><name>English</name><detail>Detail.</detail></trophy></trophyconf>')
        brazil = english.replace(b'English', 'Português'.encode())
        with tempfile.TemporaryDirectory() as directory:
            game = Path(directory)
            path = game / 'sce_sys/trophy/trophy00.trp'
            path.parent.mkdir(parents=True)
            path.write_bytes(self.archive_with_text(key, {'TROP.ESFM': english, 'TROP_17.ESFM': brazil}))
            self.assertEqual(history.catalog_text(game, '', 1), {})
            self.assertEqual(history.catalog_text(game, key.hex(), 1)[0]['name'], 'English')
            self.assertEqual(history.catalog_text(game, key.hex(), 17)[0]['name'], 'Português')
            self.assertEqual(history.catalog_text(game, key.hex(), 1)[0]['grade'], 'bronze')
            with self.assertRaisesRegex(ValueError, 'does not decrypt'):
                history.catalog_text(game, '00' * 16, 1)
            with self.assertRaisesRegex(ValueError, '32 hexadecimal'):
                history.catalog_text(game, 'not-a-key', 1)
            # The icon reader still accepts the archive with encrypted entries in it.
            self.assertEqual(len(history.catalog(game)), 1)
