"""The six accepted editions and their system-language substitutes (#113)."""
import re
import unittest
import xml.etree.ElementTree as ET

from paths import ROOT
import order1886_editions as editions


class EditionTests(unittest.TestCase):
    def test_the_editions_are_the_ones_the_published_patch_lists(self):
        document = ET.parse(ROOT / 'patches/TheOrder1886-Orbis.xml').getroot()
        self.assertEqual(sorted(node.text for node in document.findall('./TitleID/ID')), sorted(editions.TITLE_IDS))

    def test_the_native_runtime_accepts_the_same_editions(self):
        source = (ROOT / 'src/runtime_trophies.c').read_text(encoding='utf-8')
        listed = re.search(r'int runtime_order_title.*?ids\[\] = \{([^}]*)\}', source, re.S)[1]
        self.assertEqual(sorted(editions.TITLE_IDS), sorted(re.findall(r'"(CUSA\d{5})"', listed)))

    def test_only_the_verified_edition_is_not_experimental(self):
        self.assertEqual([title for title in editions.TITLE_IDS if not editions.experimental(title)],
                         [editions.VERIFIED_TITLE_ID])
        self.assertFalse(editions.supported('CUSA00207'))
        self.assertFalse(editions.experimental('CUSA00207'))

    def test_brazilian_portuguese_is_requested_as_chosen_in_every_edition(self):
        # The prepared image drops the executable's SKU language filter, so no edition
        # substitutes Portugal's Portuguese (7) for Brazilian Portuguese (17) any more.
        for title in editions.TITLE_IDS + ('CUSA00207',):
            with self.subTest(title=title):
                self.assertEqual(editions.system_language(title, 17), 17)
                self.assertEqual(editions.system_language(title, 1), 1)


if __name__ == '__main__':
    unittest.main()
