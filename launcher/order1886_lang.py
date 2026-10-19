# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure table lookup adapted from bloodborne_pc/launcher/bbport_lang.py.

Donor revision: 52e4988f54b0626447563874bf8695633b1a4302 (GPL-2.0-or-later).
Order uses an explicit saved language, English by default, rather than OS locale.
See order1886_lang_data.py for per-language reused keys and translation provenance,
order1886_lang_ui.py for the keys the Go frontend and the settings catalogue show, and
order1886_lang_ui_translations.py for the translated part of those keys.
"""
from launcher.order1886_lang_data import KEYS, TRANSLATIONS
from launcher.order1886_lang_ui import UI_KEYS
from launcher.order1886_lang_ui_translations import UI_TRANSLATIONS


LANGUAGES = {
    "en": "English", "ru": "Русский", "ar": "العربية", "es": "Español",
    "pt": "Português (Brasil)", "fr": "Français", "de": "Deutsch", "it": "Italiano",
    "pl": "Polski", "tr": "Türkçe", "zh": "简体中文", "ja": "日本語", "ko": "한국어",
}
_tables = {}


def catalogue(language):
    """Every key the launcher can show, using the English text as the fallback.

    The base tables were written for the previous Tk launcher. UI_KEYS covers the Go
    frontend and the settings catalogue, whose strings were previously not catalogued
    at all and therefore silently fell back to English in every language. The
    high-traffic subset of those keys is translated last, so it wins over the fallback
    and `untranslated()` keeps counting only the keys that are still English.
    """
    language = language if isinstance(language, str) and language in LANGUAGES else "en"
    texts = KEYS if language == "en" else TRANSLATIONS[language]
    if len(texts) != len(KEYS):
        raise ValueError(f"launcher translation {language}: {len(texts)} texts for {len(KEYS)} keys")
    merged = dict(zip(KEYS, texts))
    for key in UI_KEYS:
        merged.setdefault(key, key)
    if language != "en":
        merged.update(UI_TRANSLATIONS.get(language, {}))
    return merged


def table(language):
    """English text to translation; unknown languages use the English catalog."""
    language = language if isinstance(language, str) and language in LANGUAGES else "en"
    if language not in _tables:
        _tables[language] = catalogue(language)
    return _tables[language]


def untranslated(language):
    """Keys still shown in English for this language; the count can only go down.

    English is the source language, so it has nothing untranslated by definition.
    """
    if language not in LANGUAGES or language == "en":
        return []
    return sorted(key for key in UI_KEYS if table(language).get(key) == key)


def translate(text, language="en", **values):
    text = table(language).get(text, text)
    return text.format(**values) if values else text
