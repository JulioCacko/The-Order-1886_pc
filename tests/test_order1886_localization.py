"""Launcher language checks use temporary settings and Tk, never game/Steam state."""
import os
import ast
from pathlib import Path
import string
import tempfile
import unittest
from unittest.mock import patch

from launcher import order1886_lang as lang
from launcher import order1886_common as launcher


class CatalogTests(unittest.TestCase):
    def test_ui_language_reaches_game_system_language(self):
        expected = {"en": 1, "ru": 8, "ar": 21, "es": 3, "pt": 17, "fr": 2,
                    "de": 4, "it": 5, "pl": 16, "tr": 19, "zh": 11, "ja": 0, "ko": 9}
        for locale, code in expected.items():
            values = {"game_dir": "game", "display_mode": "windowed", "vsync": True,
                      "show_fps": False, "ui_language": locale}
            command = launcher.backend_command(values, "verify")
            self.assertEqual(command[command.index("--system-language") + 1], str(code))

    def test_literal_ui_translations_are_cataloged_without_donor_game_claims(self):
        source = ast.parse(Path(launcher.__file__).read_text(encoding="utf-8"))
        for call in ast.walk(source):
            if not isinstance(call, ast.Call) or not call.args:
                continue
            name = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")
            if name in ("tr", "translate") and isinstance(call.args[0], ast.Constant):
                text = call.args[0].value
                if isinstance(text, str) and text != "The Order: 1886":
                    self.assertIn(text, lang.KEYS)
        for locale in lang.LANGUAGES:
            for text in lang.table(locale).values():
                self.assertNotIn("CUSA03173", text)
                self.assertNotIn("Bloodborne", text)
                self.assertNotIn("shadNet", text)

    def test_thirteen_complete_catalogs_and_format_fields(self):
        self.assertEqual(set(lang.LANGUAGES), set("en ru ar es pt fr de it pl tr zh ja ko".split()))
        formatter = string.Formatter()
        fields = lambda text: sorted((field, spec, conversion) for _, field, spec, conversion
                                     in formatter.parse(text) if field is not None)
        for locale in lang.LANGUAGES:
            catalog = lang.table(locale)
            # UI_KEYS covers the Go frontend and the settings catalogue; those keys exist
            # in every language with the English text until a reviewed translation lands.
            self.assertEqual(set(catalog), set(lang.KEYS) | set(lang.UI_KEYS), locale)
            for key, value in catalog.items():
                with self.subTest(locale=locale, key=key):
                    self.assertTrue(value.strip())
                    self.assertEqual(fields(value), fields(key))

    def test_fallback_is_english_and_brand_is_not_translated(self):
        self.assertEqual(lang.translate("Play", "unsupported"), "Play")
        self.assertEqual(lang.translate("The Order: 1886", "ja"), "The Order: 1886")
        self.assertEqual(lang.translate("Session failed (exit {code})", "en", code=23),
                         "Session failed (exit 23)")
        self.assertEqual(lang.translate("Play", ["invalid"]), "Play")

    def test_preflight_instruction_is_localized_but_backend_details_survive(self):
        import order1886
        with patch.object(order1886, "inspect_game", return_value={"APP_VER": "01.00", "VERSION": "01.02"}), \
             patch.object(order1886.timing, "validate_source", side_effect=ValueError("SHA256 mismatch: abc123")):
            with self.assertRaises(ValueError) as caught:
                launcher.validate_launch_game(Path("missing-game"), {"ui_language": "ja"})
        text = str(caught.exception)
        self.assertIn("01.00", text)
        self.assertIn("01.02", text)
        self.assertIn("SHA256 mismatch: abc123", text)
        self.assertNotIn("Select 30 FPS", text)

    def test_defaults_and_unknown_settings_survive_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            values = launcher.load_launch_settings(state, {})
            self.assertEqual(values["ui_language"], "en")
            saved = dict(values, ui_language="ar", frame_rate=60, aspect_ratio="16:9",
                         future_setting={"keep": [1, 2]}, game_dir=str(state / "missing-game"))
            launcher.save_settings(state / "settings.json", saved)
            self.assertEqual(launcher.load_launch_settings(state), saved)
            command = launcher.backend_command(saved)
            self.assertEqual(command[command.index("--frame-rate") + 1], "60")
            self.assertEqual(command[command.index("--aspect-ratio") + 1], "16:9")
            self.assertNotIn("--ui-language", command)


@unittest.skipUnless(os.name == "nt", "Native Windows Tk language controls")


if __name__ == '__main__':
    unittest.main()
