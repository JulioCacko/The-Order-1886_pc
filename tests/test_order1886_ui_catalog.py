"""Every string the shipping launcher can show must be catalogued, in every language."""
import re
from pathlib import Path
import unittest

from launcher import order1886_lang as lang
from launcher.order1886_options import FIELDS, PAGES

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / 'launcher-go/frontend/src'
LITERAL = re.compile(r"\bt\(\s*'((?:[^'\\]|\\.)*)'\s*\)")


def frontend_strings():
    texts = set()
    for name in ('main.ts', 'updates.ts', 'session-status.ts', 'achievement-list.ts', 'timing-panel.ts'):
        path = FRONTEND / name
        if path.is_file():
            texts.update(match.group(1) for match in LITERAL.finditer(path.read_text(encoding='utf-8')))
    return texts


def option_strings():
    texts = {page['title'] for page in PAGES}
    for field in FIELDS:
        texts.add(field['label'])
        texts.add(field['description'])
        if field.get('reason'):
            texts.add(field['reason'])
        for choice in field.get('choices', []):
            texts.add(choice['label'])
            if choice.get('reason'):
                texts.add(choice['reason'])
            for button in field.get('buttons', []) or []:
                texts.add(button['label'])
    return texts


class UiCatalogTests(unittest.TestCase):
    def test_every_frontend_string_is_catalogued_in_every_language(self):
        wanted = frontend_strings()
        self.assertGreater(len(wanted), 100, 'the frontend scan found almost nothing')
        for locale in lang.LANGUAGES:
            table = lang.table(locale)
            missing = sorted(text for text in wanted if text not in table)
            self.assertFalse(missing, f'{locale} is missing {len(missing)} frontend strings: {missing[:5]}')

    def test_every_settings_string_is_catalogued_in_every_language(self):
        wanted = option_strings()
        self.assertGreater(len(wanted), 150, 'the settings scan found almost nothing')
        for locale in lang.LANGUAGES:
            table = lang.table(locale)
            missing = sorted(text for text in wanted if text not in table)
            self.assertFalse(missing, f'{locale} is missing {len(missing)} settings strings: {missing[:5]}')

    def test_no_language_resolves_a_key_to_nothing(self):
        for locale in lang.LANGUAGES:
            for key in lang.UI_KEYS:
                with self.subTest(locale=locale, key=key):
                    self.assertTrue(lang.table(locale).get(key, '').strip())

    def test_untranslated_keys_are_counted_and_can_only_shrink(self):
        # The numbers below are the honest state after cataloguing the Go UI and
        # translating the high-traffic subset in order1886_lang_ui_translations.py: 75
        # of the 261 UI keys are translated and 186 are still English on purpose.
        # A translator makes these go down; adding a new English-only string must not
        # make them go up unnoticed. See docs/order1886-localization-policy.md.
        expected = {locale: len(lang.UI_KEYS) - 75 for locale in lang.LANGUAGES if locale != 'en'}
        for locale, count in expected.items():
            with self.subTest(locale=locale):
                self.assertEqual(len(lang.untranslated(locale)), count)
        self.assertEqual(lang.untranslated('en'), [])

    def test_english_is_the_source_text(self):
        for key in lang.UI_KEYS:
            self.assertEqual(lang.table('en')[key], key)

    def test_unknown_language_falls_back_to_english(self):
        self.assertEqual(lang.table('xx'), lang.table('en'))


if __name__ == '__main__':
    unittest.main()
