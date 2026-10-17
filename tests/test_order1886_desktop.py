"""Desktop navigation and real save boundaries, without starting a game or GPU."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("order_desktop", ROOT / "launcher/order1886_launcher.py")
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


@unittest.skipUnless(os.name == "nt", "Windows desktop launcher")
class DesktopTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.temporary = tempfile.TemporaryDirectory(prefix="Order desktop test ")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.state, self.game = self.base / "state", self.base / "game"
        self.game.mkdir()
        self.original = self.game / "eboot.bin"
        self.original.write_bytes(b"original game must not change")
        launcher.save_settings(self.state / "settings.json", {"game_dir": str(self.game)})
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.app = launcher.DesktopLauncher(self.root, self.state)

    def test_navigation_and_escape_preserve_unsaved_changes_without_writing(self):
        before = (self.state / "settings.json").read_bytes()
        self.assertEqual(tuple(self.app.page_buttons), launcher.PAGES)
        self.app.page_fields["frame_rate"].set(60)
        for page in launcher.PAGES:
            self.app.show_page(page)
            self.root.update()
            self.assertEqual(self.app.current_page, page)
        self.app.back()
        self.assertEqual(self.app.current_page, "home")
        self.assertFalse(self.app.page_host.winfo_ismapped())
        self.assertEqual(self.app.page_fields["frame_rate"].get(), 60)
        self.assertEqual((self.state / "settings.json").read_bytes(), before)

    def test_page_settings_reach_backend_and_footer_edits_reach_pages(self):
        for key, value in {"display_mode": "windowed", "presentation_filter": "linear",
                "frame_rate": 60, "aspect_ratio": "original", "show_fps": False}.items():
            self.app.page_fields[key].set(value)
        self.assertTrue(self.app.save_page_settings())
        saved = launcher.read_settings(self.state / "settings.json")
        command = launcher.backend_command(saved, state=self.state)
        for flag, value in (("--display-mode", "windowed"), ("--presentation-filter", "linear"),
                ("--frame-rate", "60"), ("--aspect-ratio", "original"), ("--show-fps", "0")):
            self.assertEqual(command[command.index(flag) + 1], value)
        self.app.home_fields["frame_rate"].set("30 FPS")
        self.assertTrue(self.app.commit_home())
        self.assertEqual(self.app.page_fields["frame_rate"].get(), 30)
        self.assertEqual(self.original.read_bytes(), b"original game must not change")

    def test_save_changes_blocked_during_session_and_state_inside_game_rejected(self):
        before = (self.state / "settings.json").read_bytes()
        self.app.busy = True
        self.app.draw()
        self.assertTrue(all(str(w.cget("state")) == "disabled" for w in self.app.page_controls))
        self.assertFalse(self.app.save_page_settings())
        with patch("order1886.save_backup.backup") as backup:
            self.app.backup_saves()
            backup.assert_not_called()
        self.assertEqual((self.state / "settings.json").read_bytes(), before)
        self.app.busy = False
        self.app.page_fields["game_dir"].set(str(self.base))
        with patch("tkinter.messagebox.showerror") as error:
            self.assertFalse(self.app.save_page_settings())
            error.assert_called_once()
        self.assertEqual((self.state / "settings.json").read_bytes(), before)

    def test_restore_uses_real_backup_and_retains_replaced_save(self):
        savedata = self.state / "savedata" / "CUSA00076"
        savedata.mkdir(parents=True)
        save = savedata / "SYSTEM.DAT"
        save.write_bytes(b"first save")
        self.app.backup_saves()
        name = self.app.backup_list.get(0)
        save.write_bytes(b"later save")
        self.app.backup_list.selection_set(0)
        with patch("tkinter.messagebox.askyesno", return_value=False):
            self.app.restore_saves()
        self.assertEqual(save.read_bytes(), b"later save")
        with patch("tkinter.messagebox.askyesno", return_value=True):
            self.app.restore_saves()
        self.assertEqual(save.read_bytes(), b"first save")
        backups = list((self.state / "savedata_backups").glob("*/CUSA00076/SYSTEM.DAT"))
        self.assertIn(b"later save", [p.read_bytes() for p in backups])
        self.assertTrue((self.state / "savedata_backups" / name).is_dir())
        self.assertEqual(self.original.read_bytes(), b"original game must not change")

    def test_play_from_settings_saves_then_uses_existing_session_runner(self):
        self.app.show_page("performance")
        self.app.page_fields["frame_rate"].set(60)
        with patch.object(launcher.Launcher, "run") as run:
            self.app.run("play")
        run.assert_called_once_with("play")
        self.assertEqual(self.app.values["frame_rate"], 60)


if __name__ == "__main__":
    unittest.main()
