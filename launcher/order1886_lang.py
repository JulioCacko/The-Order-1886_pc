# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure table lookup adapted from bloodborne_pc/launcher/bbport_lang.py.

Donor revision: 52e4988f54b0626447563874bf8695633b1a4302 (GPL-2.0-or-later).
Order uses an explicit saved language, English by default, rather than OS locale.
See order1886_lang_data.py for per-language reused keys and translation provenance.
"""
from launcher.order1886_lang_data import KEYS, TRANSLATIONS


LANGUAGES = {
    "en": "English", "ru": "Русский", "ar": "العربية", "es": "Español",
    "pt": "Português (Brasil)", "fr": "Français", "de": "Deutsch", "it": "Italiano",
    "pl": "Polski", "tr": "Türkçe", "zh": "简体中文", "ja": "日本語", "ko": "한국어",
}
_tables = {}


def table(language):
    """English text to translation; unknown languages use the English catalog."""
    language = language if isinstance(language, str) and language in LANGUAGES else "en"
    if language not in _tables:
        texts = KEYS if language == "en" else TRANSLATIONS[language]
        if len(texts) != len(KEYS):
            raise ValueError(f"launcher translation {language}: {len(texts)} texts for {len(KEYS)} keys")
        _tables[language] = dict(zip(KEYS, texts))
    return _tables[language]


def translate(text, language="en", **values):
    text = table(language).get(text, text)
    return text.format(**values) if values else text
