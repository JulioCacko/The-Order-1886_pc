"""Register the direct-play executable in a closed Windows Steam client.

No third-party VDF parser is needed. Supported binary values are retained as
raw bytes, including unknown fields; unsupported types fail before any write.
The caller should tell the player to open Steam after a successful update.
"""
from __future__ import annotations

import csv
import ntpath
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import zlib

APP_NAME = "The Order: 1886"
_STEAM_ID_BASE = 76561197960265728
_MAX_FILE_SIZE = 64 * 1024 * 1024


class SteamIntegrationError(RuntimeError):
    """An actionable failure; existing Steam shortcuts remain untouched."""


def _steam_running() -> bool:
    if os.name != "nt":
        raise SteamIntegrationError("Steam shortcut integration currently supports Windows only.")
    try:
        result = subprocess.run(
            ["tasklist.exe", "/FI", "IMAGENAME eq steam.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10, creationflags=subprocess.CREATE_NO_WINDOW, check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SteamIntegrationError("Could not check whether Steam is running. Close Steam and retry.") from exc
    return any(row and row[0].casefold() == "steam.exe" for row in csv.reader(result.stdout.splitlines()))


def _require_closed() -> None:
    if _steam_running():
        raise SteamIntegrationError("Close Steam completely (Steam > Exit), then retry Add to Steam.")


def _find_steam_root() -> Path:
    if os.name != "nt":
        raise SteamIntegrationError("Steam shortcut integration currently supports Windows only.")
    import winreg

    candidates = []
    locations = [(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                 (winreg.HKEY_LOCAL_MACHINE, r"Software\Valve\Steam", "InstallPath"),
                 (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Valve\Steam", "InstallPath")]
    for hive, key_name, value_name in locations:
        try:
            with winreg.OpenKey(hive, key_name) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
            if isinstance(value, str) and value:
                candidates.append(Path(value))
        except OSError:
            pass
    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        if os.environ.get(variable):
            candidates.append(Path(os.environ[variable]) / "Steam")
    for candidate in candidates:
        if (candidate / "steam.exe").is_file() and (candidate / "userdata").is_dir():
            return candidate.resolve()
    raise SteamIntegrationError("Steam installation was not found. Install Steam and sign in once, then close it.")


def _read_login_users(path: Path) -> dict:
    """Read Steam's quoted, text KeyValues format without losing Unicode."""
    data = path.read_text(encoding="utf-8-sig")
    token = re.compile(r'\s+|//[^\n]*|"(?:\\.|[^"\\])*"|[{}]')
    tokens, cursor = [], 0
    while cursor < len(data):
        match = token.match(data, cursor)
        if match is None:
            raise SteamIntegrationError("Steam loginusers.vdf is malformed; sign in to Steam again and close it.")
        word = match.group()
        if not word.isspace() and not word.startswith("//"):
            tokens.append(word)
        cursor = match.end()
    position = 0

    def parse(nested=False, depth=0):
        nonlocal position
        if depth > 32:
            raise SteamIntegrationError("Steam loginusers.vdf is nested too deeply.")
        result = {}
        while position < len(tokens):
            key = tokens[position]
            position += 1
            if key == "}" and nested:
                return result
            if not key.startswith('"') or position >= len(tokens):
                break
            key = re.sub(r'\\(["\\])', r'\1', key[1:-1]).casefold()
            value = tokens[position]
            position += 1
            if key in result:
                raise SteamIntegrationError("Steam loginusers.vdf contains duplicate account fields.")
            if value == "{":
                result[key] = parse(True, depth + 1)
            elif value.startswith('"'):
                result[key] = re.sub(r'\\(["\\])', r'\1', value[1:-1])
            else:
                break
        else:
            if not nested:
                return result
        raise SteamIntegrationError("Steam loginusers.vdf is malformed; sign in to Steam again and close it.")

    document = parse()
    users = document.get("users")
    if not isinstance(users, dict):
        raise SteamIntegrationError("Steam loginusers.vdf does not contain an account list.")
    return users


def _account_directory(root: Path) -> Path:
    userdata = root / "userdata"
    available = {p.name: p for p in userdata.iterdir()
                 if p.is_dir() and p.name.isascii() and p.name.isdecimal() and int(p.name) > 0}
    login_file = root / "config/loginusers.vdf"
    if login_file.exists():
        recent = []
        for steam_id, account in _read_login_users(login_file).items():
            if not isinstance(account, dict) or not steam_id.isascii() or not steam_id.isdecimal():
                raise SteamIntegrationError("Steam loginusers.vdf has an invalid account record.")
            account_id = int(steam_id) - _STEAM_ID_BASE
            if not 0 < account_id < 2**32:
                raise SteamIntegrationError("Steam loginusers.vdf has an unsupported account ID.")
            if account.get("mostrecent") == "1":
                recent.append(str(account_id))
        if len(recent) > 1:
            raise SteamIntegrationError("Ambiguous Steam account: more than one most recent login. Sign in again, then exit Steam.")
        if recent:
            if recent[0] not in available:
                raise SteamIntegrationError("The most recent Steam account has no userdata folder. Sign in to Steam once, then exit it.")
            return available[recent[0]]
    if len(available) == 1:
        return next(iter(available.values()))
    if not available:
        raise SteamIntegrationError("No Steam account was found. Sign in to Steam once, then exit it.")
    raise SteamIntegrationError("Ambiguous Steam account. Sign in with the intended account, then exit Steam and retry.")


class _Field:
    def __init__(self, kind, name, value):
        self.kind, self.name, self.value = kind, name, value


def _parse_binary(data: bytes) -> list:
    cursor = 0

    def take(size):
        nonlocal cursor
        if cursor + size > len(data):
            raise SteamIntegrationError("Steam shortcuts.vdf is truncated; it was not changed.")
        value = data[cursor:cursor + size]
        cursor += size
        return value

    def string():
        nonlocal cursor
        end = data.find(b"\0", cursor)
        if end < 0:
            raise SteamIntegrationError("Steam shortcuts.vdf has an unterminated string; it was not changed.")
        value = data[cursor:end]
        cursor = end + 1
        return value

    def fields(depth=0):
        if depth > 32:
            raise SteamIntegrationError("Steam shortcuts.vdf is nested too deeply; it was not changed.")
        result = []
        while True:
            kind = take(1)[0]
            if kind == 8:
                return result
            name = string()
            if kind == 0:
                value = fields(depth + 1)
            elif kind == 1:
                value = string() + b"\0"
            elif kind in (2, 3, 4, 6, 7):
                value = take(8 if kind == 7 else 4)
            else:
                raise SteamIntegrationError(f"Steam shortcuts.vdf uses unsupported type {kind}; it was not changed.")
            result.append(_Field(kind, name, value))

    result = fields()
    if cursor != len(data):
        raise SteamIntegrationError("Steam shortcuts.vdf contains trailing data; it was not changed.")
    return result


def _encode_binary(fields: list) -> bytes:
    return b"".join(bytes([f.kind]) + f.name + b"\0" +
                    (_encode_binary(f.value) if f.kind == 0 else f.value) for f in fields) + b"\x08"


def _field(fields: list, name: bytes):
    found = [f for f in fields if f.name.lower() == name.lower()]
    if len(found) > 1:
        raise SteamIntegrationError("Steam shortcuts.vdf contains ambiguous duplicate fields; it was not changed.")
    return found[0] if found else None


def _text(fields: list, name: bytes) -> str:
    field = _field(fields, name)
    if field is None:
        return ""
    if field.kind != 1:
        raise SteamIntegrationError("Steam shortcuts.vdf contains an invalid shortcut string; it was not changed.")
    return field.value[:-1].decode("utf-8", errors="surrogateescape")


def _set(fields: list, name: bytes, value, kind=1):
    encoded = value.encode("utf-8") + b"\0" if kind == 1 else value
    field = _field(fields, name)
    if field is None:
        fields.append(_Field(kind, name, encoded))
    else:
        field.kind, field.value = kind, encoded


def _updated_shortcuts(before: bytes | None, installation: Path, state: Path | None) -> bytes:
    document = _parse_binary(before) if before is not None else [_Field(0, b"shortcuts", [])]
    shortcuts = _field(document, b"shortcuts")
    if shortcuts is None or shortcuts.kind != 0:
        raise SteamIntegrationError("Steam shortcuts.vdf has no valid shortcuts object; it was not changed.")
    exe = f'"{installation / "Play The Order 1886.exe"}"'
    matches, indexes = [], set()
    for item in shortcuts.value:
        if item.kind != 0 or not item.name.isdigit() or item.name in indexes:
            raise SteamIntegrationError("Steam shortcuts.vdf has invalid or duplicate shortcut indexes; it was not changed.")
        indexes.add(item.name)
        name, target = _text(item.value, b"AppName"), _text(item.value, b"Exe")
        target_path = target.strip('"')
        if (ntpath.normcase(ntpath.normpath(target_path)) == ntpath.normcase(ntpath.normpath(exe.strip('"')))
                or (name in (APP_NAME, "The Order 1886") and
                    ntpath.basename(target_path).casefold() in
                    ("play the order 1886.exe", "the order 1886.exe", ""))):
            matches.append(item.value)
    if len(matches) > 1:
        raise SteamIntegrationError("Multiple The Order Steam shortcuts match. Remove duplicate entries in Steam, then retry.")
    if matches:
        entry = matches[0]
    else:
        entry = []
        index = max((int(i) for i in indexes), default=-1) + 1
        shortcuts.value.append(_Field(0, str(index).encode("ascii"), entry))
        for key, value in ((b"IsHidden", 0), (b"AllowDesktopConfig", 1), (b"AllowOverlay", 1),
                           (b"OpenVR", 0), (b"Devkit", 0), (b"DevkitOverrideAppID", 0), (b"LastPlayTime", 0)):
            _set(entry, key, struct.pack("<I", value), 2)
        _set(entry, b"ShortcutPath", "")
        _set(entry, b"DevkitGameID", "")
        _set(entry, b"tags", [], 0)
    appid = _field(entry, b"appid")
    if appid is not None and appid.kind != 2:
        raise SteamIntegrationError("Steam shortcut has an invalid appid; it was not changed.")
    if appid is None:
        _set(entry, b"appid", struct.pack("<I", zlib.crc32((exe + APP_NAME).encode("utf-8")) | 0x80000000), 2)
    for key, value in ((b"AppName", APP_NAME), (b"Exe", exe), (b"StartDir", f'"{installation}"'),
                       (b"icon", f'"{installation / "The Order 1886.exe"}"'),
                       (b"LaunchOptions", subprocess.list2cmdline(["--state-dir", str(state)]) if state is not None else "")):
        _text(entry, key)  # Reject a malformed owned field before replacing it.
        _set(entry, key, value)
    return _encode_binary(document)


def _write_shortcuts(path: Path, before: bytes | None, after: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix="shortcuts.", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            output.write(after)
            output.flush()
            os.fsync(output.fileno())
        _require_closed()
        current = path.read_bytes() if path.exists() else None
        if current != before:
            raise SteamIntegrationError("Steam shortcuts changed while adding the game. Close Steam and retry.")
        if before is not None:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix="shortcuts.", suffix=".bak", delete=False) as backup:
                backup.write(before)
                backup.flush()
                os.fsync(backup.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def add_to_steam(installation: Path, steam_root: Path | None = None, *, state: Path | None = None) -> Path:
    """Add/update one shortcut, returning its shortcuts.vdf path.

    Steam must be closed. Existing app IDs and unrelated fields are retained;
    each changed existing file receives a unique sibling ``shortcuts.*.bak``.
    Repeated calls with unchanged paths do not write or create another backup.
    Raises SteamIntegrationError for discovery, validation, or filesystem errors.
    """
    try:
        installation = Path(installation).resolve()
        if state is not None:
            state = Path(state).resolve()
            if any(character in str(state) for character in ('"', "\0", "\r", "\n")):
                raise SteamIntegrationError("The state path contains characters unsupported by Steam shortcuts.")
        if any(character in str(installation) for character in ('"', "\0", "\r", "\n")):
            raise SteamIntegrationError("The installation path contains characters unsupported by Steam shortcuts.")
        for name in ("Play The Order 1886.exe", "The Order 1886.exe"):
            if not (installation / name).is_file():
                raise SteamIntegrationError(f"Missing {name}. Use the packaged Windows installation to add the game to Steam.")
        _require_closed()
        root = Path(steam_root).resolve() if steam_root is not None else _find_steam_root()
        if not (root / "steam.exe").is_file() or not (root / "userdata").is_dir():
            raise SteamIntegrationError("Invalid Steam installation. Install Steam and sign in once, then exit it.")
        path = _account_directory(root) / "config/shortcuts.vdf"
        if path.exists() and path.stat().st_size > _MAX_FILE_SIZE:
            raise SteamIntegrationError("Steam shortcuts.vdf is too large to safely update; it was not changed.")
        before = path.read_bytes() if path.exists() else None
        after = _updated_shortcuts(before, installation, state)
        if after != before:
            _write_shortcuts(path, before, after)
        return path
    except (OSError, UnicodeError, ValueError) as exc:
        raise SteamIntegrationError(f"Could not add The Order to Steam: {exc}") from exc
