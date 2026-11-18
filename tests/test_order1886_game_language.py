"""Game language: the always-on SKU recipe and the editions fallback (synthetic images only)."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import order1886_editions as editions
import order1886_patches as patches

IMAGE_SIZE = 0xb00000


def prepared(path, table_bytes):
    """A PS4BOOT2 image holding these bytes at the SKU jump table."""
    ns, nr, ni = 1, 1, 1
    start = 56 + ns * 24 + ni * 128 + nr * 32
    data = bytearray(start + IMAGE_SIZE)
    struct.pack_into('<8s6Q', data, 0, b'PS4BOOT2', IMAGE_SIZE, 0xa0, ns, nr, ni, 1)
    data[start + patches.LANGUAGE_TABLE_RVA:start + patches.LANGUAGE_TABLE_RVA + 4] = table_bytes
    Path(path).write_bytes(data)
    return start


class GameLanguageTests(unittest.TestCase):
    def test_recipe_is_always_selected_and_never_listed(self):
        for title in editions.TITLE_IDS:
            chosen = patches.select([], {'TITLE_ID': title})
            self.assertEqual([r['id'] for r in chosen], ['system-language-unfiltered'])
        self.assertEqual(patches.select([], {'TITLE_ID': 'CUSA99999'}), ())
        self.assertNotIn(patches.LANGUAGE, patches.RECIPES)
        with self.assertRaises(ValueError):
            patches.validate_selection(['system-language-unfiltered'])

    def test_sku0_entry_is_pointed_at_the_direct_store(self):
        # Entry 0 jumps to 0xa81687 (SKU 0 filter), entry 3 to 0xa81698 (store). Both are
        # rel32 offsets from the table at 0xa81b00.
        edit, = patches.LANGUAGE['edits']
        self.assertEqual(struct.unpack('<i', edit['expected'])[0], 0xa81687 - 0xa81b00)
        self.assertEqual(struct.unpack('<i', edit['replacement'])[0], 0xa81698 - 0xa81b00)
        with tempfile.TemporaryDirectory() as folder:
            boot = Path(folder) / 'boot.bin'
            start = prepared(boot, edit['expected'])
            applied = patches.apply_to_prepared(boot, [patches.LANGUAGE], {'TITLE_ID': 'CUSA00035'})
            self.assertEqual(applied[0]['edits'][0]['after'], '98fbffff')
            at = start + patches.LANGUAGE_TABLE_RVA
            self.assertEqual(boot.read_bytes()[at:at + 4], edit['replacement'])

    def test_unexpected_bytes_are_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            boot = Path(folder) / 'boot.bin'
            prepared(boot, b'\0\0\0\0')
            with self.assertRaisesRegex(ValueError, 'expected bytes are absent'):
                patches.apply_to_prepared(boot, [patches.LANGUAGE], {'TITLE_ID': 'CUSA00035'})

    def test_no_language_is_substituted(self):
        for title in editions.TITLE_IDS:
            for language in range(30):
                self.assertEqual(editions.system_language(title, language), language)


if __name__ == '__main__':
    unittest.main()
