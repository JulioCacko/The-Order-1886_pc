"""The high-traffic UI subset must be translated for real, not merely catalogued.

`launcher/order1886_lang_ui_translations.py` deliberately covers only the low-risk
navigation, heading, button and short-label strings. These tests pin three things: the
subset stays inside `UI_KEYS`, every entry is a genuine translation without a diagnostic
term in it, and `untranslated()` still reports exactly the keys that remain English.
"""
import unittest

from launcher import order1886_lang as lang
from launcher.order1886_lang_ui import UI_KEYS
from launcher.order1886_lang_ui_translations import EXCLUDED_TECHNICAL_TERMS, UI_TRANSLATIONS

QUESTION_MARKS = ("?", "\u061f", "\uff1f")
LABEL_LIMIT = 48


def problems(key, value):
    """Everything wrong with one entry; an empty list means a usable translation.

    This is a function rather than an inline assertion so the same rules a reviewer
    reads in docs/order1886-localization-policy.md are the ones the tests apply, and so
    a deliberately broken entry - an empty string, or the English text copied through -
    fails on the first rule it breaks instead of only shifting a count.
    """
    found = []
    if not isinstance(value, str) or not value.strip():
        return ["empty"]
    if value == key:
        found.append("still the English text")
    if value.strip() != value:
        found.append("stray surrounding whitespace")
    lowered = value.lower()
    for term in EXCLUDED_TECHNICAL_TERMS:
        if term.lower() in lowered:
            found.append(f"contains the excluded technical term {term!r}")
    if any(mark in value for mark in "{}%"):
        found.append("carries a placeholder the English key does not have")
    if key.endswith("?") and not any(mark in value for mark in QUESTION_MARKS):
        found.append("lost the question mark")
    if key.endswith("\u2026") and not (value.endswith("\u2026") or value.endswith("...")):
        found.append("lost the trailing ellipsis")
    if len(value) > LABEL_LIMIT:
        found.append(f"too long for a short label: {len(value)} characters")
    if "The Order" in value:
        found.append("translates the product name")
    return found


class SubsetShapeTests(unittest.TestCase):
    def test_every_locale_is_one_of_the_languages_apart_from_english(self):
        expected = set(lang.LANGUAGES) - {"en"}
        self.assertEqual(set(UI_TRANSLATIONS), expected)

    def test_every_key_is_a_catalogued_ui_key(self):
        orphans = sorted(key for texts in UI_TRANSLATIONS.values() for key in texts
                         if key not in set(UI_KEYS))
        self.assertFalse(orphans, f"not in UI_KEYS: {orphans[:5]}")

    def test_every_locale_carries_the_same_keys(self):
        reference = set(UI_TRANSLATIONS["de"])
        self.assertGreater(len(reference), 60, "the subset shrank to almost nothing")
        for locale, texts in UI_TRANSLATIONS.items():
            with self.subTest(locale=locale):
                self.assertEqual(set(texts), reference)

    def test_the_subset_itself_avoids_the_excluded_technical_terms(self):
        for key in sorted(UI_TRANSLATIONS["de"]):
            for term in EXCLUDED_TECHNICAL_TERMS:
                with self.subTest(key=key, term=term):
                    self.assertNotIn(term.lower(), key.lower(),
                                     f"{key!r} belongs in the excluded part of the policy")

    def test_no_english_key_smuggles_in_a_description(self):
        # Every key in the subset is a title, heading, button or short label: a full
        # sentence with a full stop belongs to the excluded description/reason class.
        for key in sorted(UI_TRANSLATIONS["de"]):
            with self.subTest(key=key):
                self.assertFalse(key.rstrip(")").endswith(".") and "…" not in key,
                                 f"{key!r} reads like a sentence, not a label")


class TranslationQualityTests(unittest.TestCase):
    def test_every_entry_is_a_real_translation(self):
        for locale, texts in UI_TRANSLATIONS.items():
            for key, value in texts.items():
                with self.subTest(locale=locale, key=key):
                    self.assertEqual(problems(key, value), [])

    def test_the_checker_catches_a_broken_entry(self):
        # The guard above is only worth anything if it fails loudly. These are the two
        # ways a bad entry slips in; both were also checked by hand by temporarily
        # breaking a real entry (see the pull request body).
        self.assertTrue(problems("Stop", ""), "an empty entry must not pass")
        self.assertEqual(problems("Stop", ""), ["empty"])
        self.assertEqual(problems("Cancel", "   "), ["empty"])
        self.assertIn("still the English text", problems("Cancel", "Cancel"))
        self.assertIn("lost the question mark", problems("Stop and close?", "Arreter et fermer"))
        self.assertIn("contains the excluded technical term 'GPU'",
                      problems("Stop", "GPU readback"))
        self.assertTrue(any(reason.startswith("too long for a short label")
                            for reason in problems("Stop", "x" * (LABEL_LIMIT + 1))))
        self.assertEqual(problems("Cancel", "Abbrechen"), [])


class CatalogueWiringTests(unittest.TestCase):
    def test_the_catalogue_serves_the_translated_subset(self):
        for locale, texts in UI_TRANSLATIONS.items():
            for key, value in texts.items():
                with self.subTest(locale=locale, key=key):
                    self.assertEqual(lang.table(locale)[key], value)
                    self.assertEqual(lang.translate(key, locale), value)

    def test_untranslated_reports_only_the_keys_that_are_still_english(self):
        for locale, texts in UI_TRANSLATIONS.items():
            with self.subTest(locale=locale):
                still_english = sorted(set(UI_KEYS) - set(texts))
                self.assertEqual(lang.untranslated(locale), still_english)
                self.assertEqual(len(lang.untranslated(locale)), len(UI_KEYS) - len(texts))
                self.assertLess(len(lang.untranslated(locale)), len(UI_KEYS))
        self.assertEqual(lang.untranslated("en"), [])

    def test_the_untouched_keys_stay_english_on_purpose(self):
        for locale in UI_TRANSLATIONS:
            for key in ("HTILE metadata adaptation (unqualified)", "VSync", "VBlank",
                        "GPU readback policy", "Speculative GPU readbacks"):
                with self.subTest(locale=locale, key=key):
                    self.assertEqual(lang.table(locale)[key], key)

    def test_the_product_name_and_english_source_survive(self):
        self.assertEqual(lang.translate("The Order: 1886", "ja"), "The Order: 1886")
        for locale in UI_TRANSLATIONS:
            for value in lang.table(locale).values():
                self.assertNotIn("CUSA03173", value)
                self.assertNotIn("Bloodborne", value)
        self.assertEqual(lang.table("en")["Stop"], "Stop")
        self.assertEqual(lang.table("en")["uncapped"], "uncapped")


if __name__ == "__main__":
    unittest.main()
