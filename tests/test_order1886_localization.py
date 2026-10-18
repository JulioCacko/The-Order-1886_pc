"""Launcher language checks use temporary settings and Tk, never game/Steam state."""
import os
import ast
from pathlib import Path
import string
import tempfile
import unittest
from unittest.mock import patch

from launcher import order1886_lang as lang
from launcher import order1886_launcher as launcher


class CatalogTests(unittest.TestCase):
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
            self.assertEqual(set(catalog), set(lang.KEYS), locale)
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
class LanguageUITests(unittest.TestCase):
    def test_arabic_cjk_navigation_choices_and_focus(self):
        import tkinter as tk
        for locale in ("ar", "zh", "ja", "ko"):
            with self.subTest(locale=locale), tempfile.TemporaryDirectory() as directory:
                state = Path(directory)
                launcher.save_settings(state / "settings.json", {
                    "game_dir": str(state / "missing-game"), "ui_language": locale,
                    "frame_rate": 60, "aspect_ratio": "16:9", "future": {"keep": True}})
                root = tk.Tk()
                root.withdraw()
                try:
                    app = launcher.DesktopLauncher(root, state)
                    self.assertEqual(app.page_buttons["advanced"].cget("text"),
                                     lang.translate("Advanced", locale))
                    app.home_fields["display_mode"].set(lang.translate("Windowed", locale))
                    self.assertTrue(app.commit_home())
                    saved = launcher.read_settings(state / "settings.json")
                    self.assertEqual(saved["display_mode"], "windowed")
                    self.assertEqual(saved["frame_rate"], 60)
                    self.assertEqual(saved["aspect_ratio"], "16:9")
                    self.assertEqual(saved["future"], {"keep": True})
                    app.show_page("advanced")
                    root.geometry("1120x700")
                    root.deiconify()
                    root.update()
                    self.assertEqual(str(app.language_combo.cget("state")), "readonly")
                    self.assertEqual(tuple(app.language_combo.cget("values")), tuple(lang.LANGUAGES.values()))
                    if locale == "ar":
                        self.assertEqual(app.warning.cget("justify"), "right")
                        self.assertEqual(app.page_buttons["advanced"].cget("anchor"), "e")
                    root.focus_force()
                    app.language_combo.focus_set()
                    root.update()
                    self.assertEqual(root.focus_get(), app.language_combo)
                    app.language_combo.event_generate("<Tab>")
                    root.update()
                    self.assertNotEqual(root.focus_get(), app.language_combo)
                    self.assertIsNotNone(root.focus_get())
                    for page in launcher.PAGES:
                        app.show_page(page)
                        root.update_idletasks()
                        self.assertLessEqual(app.page_buttons[page].winfo_reqwidth(), 180)
                finally:
                    root.destroy()

    def test_language_only_save_preserves_unsupported_values_and_pending_edits(self):
        import tkinter as tk
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            saved = {"game_dir": str(state / "missing-game"), "ui_language": "en",
                     "frame_rate": 144, "aspect_ratio": "future-aspect", "future": [1, 2]}
            launcher.save_settings(state / "settings.json", saved)
            root = tk.Tk()
            root.withdraw()
            try:
                app = launcher.DesktopLauncher(root, state)
                app.page_fields["runtime"].set("unsaved-runtime.exe")
                app.language_choice.set(lang.LANGUAGES["ar"])
                with patch("tkinter.messagebox.showinfo") as notice:
                    app.save_language()
                self.assertEqual(launcher.read_settings(state / "settings.json"), dict(saved, ui_language="ar"))
                self.assertEqual(app.language, "en")
                self.assertEqual(app.page_fields["runtime"].get(), "unsaved-runtime.exe")
                notice.assert_called_once()
                self.assertIn("Restart", notice.call_args.args[1])
                self.assertEqual(launcher.load_launch_settings(state)["ui_language"], "ar")
            finally:
                root.destroy()


if __name__ == "__main__":
    unittest.main()
