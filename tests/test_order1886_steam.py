"""Steam shortcut safety tests; all installation and userdata paths are temporary."""
import importlib.util
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("order_steam", ROOT / "scripts/order1886_steam.py")
steam = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(steam)


def text_field(name, value):
    return b"\x01" + name.encode() + b"\0" + value.encode("utf-8") + b"\0"


def int_field(name, value):
    return b"\x02" + name.encode() + b"\0" + struct.pack("<I", value)


def obj(name, body):
    return b"\0" + name.encode() + b"\0" + body + b"\x08"


def document(body=b""):
    return obj("shortcuts", body) + b"\x08"


def read_fields(data):
    """Independent fixture reader for the three ordinary shortcut field types."""
    cursor = 0

    def cstring():
        nonlocal cursor
        end = data.index(0, cursor)
        value = data[cursor:end].decode("utf-8")
        cursor = end + 1
        return value

    def fields():
        nonlocal cursor
        result = {}
        while True:
            kind = data[cursor]
            cursor += 1
            if kind == 8:
                return result
            name = cstring()
            if kind == 0:
                value = fields()
            elif kind == 1:
                value = cstring()
            elif kind == 2:
                value = struct.unpack_from("<I", data, cursor)[0]
                cursor += 4
            else:
                raise AssertionError("unexpected fixture field")
            if name in result:
                raise AssertionError("duplicate field")
            result[name] = value

    result = fields()
    assert cursor == len(data)
    return result


class SteamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="Order Steam test ")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.install = self.base / "Julio's instalação 日本語"
        self.install.mkdir()
        for name in ("Play The Order 1886.exe", "The Order 1886.exe"):
            (self.install / name).write_bytes(b"fixture executable")
        self.root = self.base / "Steam"
        self.root.mkdir()
        (self.root / "steam.exe").write_bytes(b"fixture Steam")
        self.config = self.root / "userdata" / "42" / "config"
        self.config.mkdir(parents=True)
        self.path = self.config / "shortcuts.vdf"
        self.closed = patch.object(steam, "_steam_running", return_value=False)
        self.closed.start()
        self.addCleanup(self.closed.stop)

    def add(self):
        return steam.add_to_steam(self.install, self.root)

    def test_custom_state_directory_is_preserved_and_updated_idempotently(self):
        state = self.base / "Custom saves Joao's \u00e7"
        steam.add_to_steam(self.install, self.root, state=state)
        entry = read_fields(self.path.read_bytes())["shortcuts"]["0"]
        self.assertEqual(entry["LaunchOptions"], f'--state-dir "{state.resolve()}"')
        before = self.path.read_bytes()
        steam.add_to_steam(self.install, self.root, state=state)
        self.assertEqual(self.path.read_bytes(), before)
        other = self.base / 'Another profile'
        steam.add_to_steam(self.install, self.root, state=other)
        entries = read_fields(self.path.read_bytes())["shortcuts"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries["0"]["LaunchOptions"], f'--state-dir "{other.resolve()}"')

    def write_logins(self, body):
        (self.root / "config").mkdir(exist_ok=True)
        (self.root / "config/loginusers.vdf").write_text('"users" { ' + body + ' }', encoding="utf-8")

    def test_missing_shortcuts_quoted_paths_and_repeat_are_idempotent(self):
        self.assertEqual(self.add(), self.path)
        raw = self.path.read_bytes()
        entry = read_fields(raw)["shortcuts"]["0"]
        self.assertEqual(entry["AppName"], "The Order: 1886")
        self.assertEqual(entry["Exe"], '"' + str(self.install / "Play The Order 1886.exe") + '"')
        self.assertEqual(entry["StartDir"], '"' + str(self.install) + '"')
        self.assertEqual(entry["icon"], '"' + str(self.install / "The Order 1886.exe") + '"')
        self.assertEqual(entry["LaunchOptions"], "")
        self.assertTrue(entry["appid"] & 0x80000000)
        self.assertEqual(entry["tags"], {})
        before_time = self.path.stat().st_mtime_ns
        self.assertEqual(self.add(), self.path)
        self.assertEqual(self.path.read_bytes(), raw)
        self.assertEqual(self.path.stat().st_mtime_ns, before_time)
        self.assertEqual(list(self.config.glob("*.bak")), [])

    def test_empty_valid_document_backed_up_before_change(self):
        before = document()
        self.path.write_bytes(before)
        self.add()
        self.assertEqual(len(read_fields(self.path.read_bytes())["shortcuts"]), 1)
        self.assertEqual([p.read_bytes() for p in self.config.glob("*.bak")], [before])

    def test_preserves_unrelated_entries_unknown_fields_order_and_raw_values(self):
        unknown = (b"\x03float\0\x01\x00\xc0\x7f" + b"\x04pointer\0abcd"
                   + b"\x06color\0\x01\x02\x03\x04" + b"\x07wideint\0abcdefgh")
        other = obj("4", text_field("AppName", "Unrelated 日本") + unknown
                    + obj("tags", text_field("0", "My favorites")))
        root_extra = text_field("unknown_root_field", "keep me")
        before = obj("shortcuts", other) + root_extra + b"\x08"
        self.path.write_bytes(before)
        self.add()
        after = self.path.read_bytes()
        self.assertIn(other, after)
        self.assertIn(root_extra, after)
        self.assertIn(b"\x005\0", after)
        self.assertEqual([p.read_bytes() for p in self.config.glob("*.bak")], [before])

    def test_update_existing_retains_appid_tags_and_user_metadata(self):
        old = (int_field("appid", 0x87654321) + text_field("appname", "The Order: 1886")
               + text_field("exe", '"D:\\old\\Play The Order 1886.exe"')
               + text_field("StartDir", "old") + text_field("icon", "old")
               + text_field("LaunchOptions", "--old-option")
               + obj("tags", text_field("0", "Favorites")) + int_field("LastPlayTime", 1234))
        self.path.write_bytes(document(obj("0", old)))
        self.add()
        entries = read_fields(self.path.read_bytes())["shortcuts"]
        self.assertEqual(len(entries), 1)
        entry = entries["0"]
        self.assertEqual(entry["appid"], 0x87654321)
        self.assertEqual(entry["tags"], {"0": "Favorites"})
        self.assertEqual(entry["LastPlayTime"], 1234)
        self.assertEqual(entry["LaunchOptions"], "")
        self.assertEqual(entry["exe"], '"' + str(self.install / "Play The Order 1886.exe") + '"')
        self.add()
        self.assertEqual(len(list(self.config.glob("*.bak"))), 1)

    def test_all_truncated_documents_rejected_without_mutation(self):
        complete = document(obj("0", text_field("AppName", "Other") + int_field("appid", 12)))
        for size in range(len(complete)):
            with self.subTest(size=size):
                truncated = complete[:size]
                self.path.write_bytes(truncated)
                with self.assertRaises(steam.SteamIntegrationError):
                    self.add()
                self.assertEqual(self.path.read_bytes(), truncated)
        self.assertEqual(list(self.config.glob("*.bak")), [])

    def test_unsupported_malformed_and_duplicate_documents_rejected(self):
        examples = [document(b"\x05unsupported\0abc"), document() + b"extra",
                    document(text_field("0", "not object")), obj("wrongroot", b"") + b"\x08",
                    document(obj("0", b"") + obj("0", b"")),
                    document(obj("0", text_field("AppName", "A") + text_field("appname", "B")))]
        for before in examples:
            with self.subTest(before=before):
                self.path.write_bytes(before)
                with self.assertRaises(steam.SteamIntegrationError):
                    self.add()
                self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.config.glob("*.bak")), [])

    def test_running_steam_refused_without_writes(self):
        self.path.write_bytes(document())
        with patch.object(steam, "_steam_running", return_value=True):
            with self.assertRaisesRegex(steam.SteamIntegrationError, "[Cc]lose Steam"):
                self.add()
        self.assertEqual(self.path.read_bytes(), document())
        self.assertEqual(list(self.config.glob("*.bak")), [])

    def test_steam_started_during_operation_refused(self):
        self.path.write_bytes(document())
        with patch.object(steam, "_steam_running", side_effect=[False, True]):
            with self.assertRaisesRegex(steam.SteamIntegrationError, "[Cc]lose Steam"):
                self.add()
        self.assertEqual(self.path.read_bytes(), document())

    def test_failed_atomic_replace_keeps_original_and_backup(self):
        self.path.write_bytes(document())
        with patch.object(steam.os, "replace", side_effect=OSError("fixture denied")):
            with self.assertRaises(steam.SteamIntegrationError):
                self.add()
        self.assertEqual(self.path.read_bytes(), document())
        self.assertEqual([p.read_bytes() for p in self.config.glob("*.bak")], [document()])
        self.assertEqual(list(self.config.glob("*.tmp")), [])

    def test_most_recent_account_selected_over_other_userdata(self):
        other = self.root / "userdata/7/config"
        other.mkdir(parents=True)
        self.write_logins('"76561197960265735" { "MostRecent" "0" } '
                          '"76561197960265770" { "MostRecent" "1" "PersonaName" "Julio\\\"s" }')
        self.assertEqual(self.add(), self.path)
        self.assertFalse((other / "shortcuts.vdf").exists())

    def test_ambiguous_account_refused(self):
        (self.root / "userdata/7/config").mkdir(parents=True)
        with self.assertRaisesRegex(steam.SteamIntegrationError, "[Aa]mbiguous"):
            self.add()
        self.assertFalse(self.path.exists())

    def test_missing_account_refused(self):
        self.config.rmdir()
        self.config.parent.rmdir()
        with self.assertRaisesRegex(steam.SteamIntegrationError, "account|[Ss]ign in"):
            self.add()
        self.assertFalse(self.path.exists())

    def test_malformed_logins_and_missing_most_recent_userdata_refused(self):
        for body in ('"bad" {', '"76561197960265735" { "MostRecent" "1" }'):
            self.write_logins(body)
            with self.assertRaises(steam.SteamIntegrationError):
                self.add()
        self.assertFalse(self.path.exists())

    def test_missing_direct_play_binary_refused(self):
        (self.install / "Play The Order 1886.exe").unlink()
        with self.assertRaisesRegex(steam.SteamIntegrationError, "Play The Order 1886.exe"):
            self.add()
        self.assertFalse(self.path.exists())

    def test_default_root_uses_detection(self):
        with patch.object(steam, "_find_steam_root", return_value=self.root) as detect:
            self.assertEqual(steam.add_to_steam(self.install), self.path)
        detect.assert_called_once_with()

    def test_unrelated_same_display_name_is_not_overwritten(self):
        other = obj("0", text_field("AppName", "The Order: 1886") + text_field("Exe", '"D:\\Other.exe"'))
        self.path.write_bytes(document(other))
        self.add()
        self.assertIn(other, self.path.read_bytes())
        self.assertEqual(len(read_fields(self.path.read_bytes())["shortcuts"]), 2)

    def test_multiple_matching_shortcuts_are_rejected(self):
        entry = text_field("AppName", "The Order: 1886") + text_field("Exe", '"D:\\Play The Order 1886.exe"')
        before = document(obj("0", entry) + obj("1", entry))
        self.path.write_bytes(before)
        with self.assertRaisesRegex(steam.SteamIntegrationError, "Multiple"):
            self.add()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.config.glob("*.bak")), [])

    def test_invalid_owned_field_type_is_rejected_without_changing_file(self):
        entry = (text_field("AppName", "The Order: 1886")
                 + text_field("Exe", '"D:\\Play The Order 1886.exe"')
                 + obj("StartDir", text_field("unexpected", "retain this")))
        before = document(obj("0", entry))
        self.path.write_bytes(before)
        with self.assertRaises(steam.SteamIntegrationError):
            self.add()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.config.glob("*.bak")), [])

    def test_concurrent_shortcut_change_is_not_overwritten(self):
        self.path.write_bytes(document())
        external_change = document(obj("0", text_field("AppName", "Another writer")))
        checks = 0

        def check_process():
            nonlocal checks
            checks += 1
            if checks == 2:
                self.path.write_bytes(external_change)
            return False

        with patch.object(steam, "_steam_running", side_effect=check_process):
            with self.assertRaisesRegex(steam.SteamIntegrationError, "changed"):
                self.add()
        self.assertEqual(self.path.read_bytes(), external_change)
        self.assertEqual(list(self.config.glob("*.bak")), [])

    def test_failed_backup_never_replaces_original(self):
        self.path.write_bytes(document())
        create = steam.tempfile.NamedTemporaryFile

        def fail_backup(*args, **kwargs):
            if kwargs.get("suffix") == ".bak":
                raise OSError("fixture full disk")
            return create(*args, **kwargs)

        with patch.object(steam.tempfile, "NamedTemporaryFile", side_effect=fail_backup):
            with self.assertRaises(steam.SteamIntegrationError):
                self.add()
        self.assertEqual(self.path.read_bytes(), document())
        self.assertEqual(list(self.config.glob("*.tmp")), [])

    @unittest.skipUnless(steam.os.name == "nt", "Windows registry discovery")
    def test_registry_and_program_files_root_detection_uses_fake_installation(self):
        registry = MagicMock()
        registry.QueryValueEx.return_value = (str(self.root), 1)
        with patch.dict(sys.modules, {"winreg": registry}), patch.dict(steam.os.environ, {}, clear=True):
            self.assertEqual(steam._find_steam_root(), self.root)
            registry.OpenKey.assert_any_call(registry.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        registry.OpenKey.side_effect = OSError("fixture registry missing")
        with patch.dict(sys.modules, {"winreg": registry}), patch.dict(
                steam.os.environ, {"ProgramFiles(x86)": str(self.base)}, clear=True):
            self.assertEqual(steam._find_steam_root(), self.root)
        with patch.dict(sys.modules, {"winreg": registry}), patch.dict(steam.os.environ, {}, clear=True):
            with self.assertRaisesRegex(steam.SteamIntegrationError, "not found"):
                steam._find_steam_root()

    @unittest.skipUnless(steam.os.name == "nt", "Windows process detection")
    def test_process_detection_handles_csv_and_fails_closed(self):
        self.closed.stop()
        with patch.object(steam.subprocess, "run", return_value=types.SimpleNamespace(
                stdout='"steam.exe","123","Console","1","123 K"\n')) as run:
            self.assertTrue(steam._steam_running())
            self.assertEqual(run.call_args.args[0][0], "tasklist.exe")
        with patch.object(steam.subprocess, "run", return_value=types.SimpleNamespace(
                stdout="INFO: No tasks are running which match the specified criteria.\n")):
            self.assertFalse(steam._steam_running())
        for error in (OSError("fixture missing command"), subprocess.TimeoutExpired("tasklist", 10)):
            with patch.object(steam.subprocess, "run", side_effect=error):
                with self.assertRaisesRegex(steam.SteamIntegrationError, "Could not check"):
                    steam._steam_running()

    def test_module_import_does_not_probe_or_mutate_steam(self):
        module = importlib.util.module_from_spec(SPEC)
        with patch.object(subprocess, "run") as run, patch.object(Path, "write_bytes") as write:
            SPEC.loader.exec_module(module)
        run.assert_not_called()
        write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
