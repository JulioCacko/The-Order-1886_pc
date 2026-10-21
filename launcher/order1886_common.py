"""Shared launcher state: settings, the backend command, sessions and shortcuts.

The Go launcher talks to this through `order1886_worker.py`; the previous Tk window used
the same helpers and is no longer shipped.
"""
from __future__ import annotations


import argparse
import base64
from collections import deque
import codecs
import io
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from typing import Protocol

FROZEN = getattr(sys, "frozen", False)
ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
BUNDLE = Path(getattr(sys, "_MEIPASS", ROOT))
ASSETS = BUNDLE / "launcher" / "order1886"
sys.path.insert(0, str(BUNDLE))
from launcher.order1886_lang import LANGUAGES, translate
STATE = ROOT / "user" / "order1886"
# Page order adapted from mateussmeneses/theorder1886-port, GPL-2.0-or-later.
# Reference: 7822ee56c2169f15ecde5d80f39e96143a252464, launcher/port_launcher_win.py.


def read_settings(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(path: Path, values: dict) -> None:
    if values.get("game_dir"):
        game = Path(values["game_dir"])
        game = (game if game.is_absolute() else ROOT / game).resolve()
        state = path.parent.resolve()
        if state == game or game in state.parents:
            raise ValueError("Launcher state must be outside the selected game folder.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def backend_command(values: dict, mode: str = "play", state: Path = STATE,
                    stop_file: Path | None = None) -> list[str]:
    from order1886 import SYSTEM_LANGUAGES, inputs
    locale = values.get("ui_language", "en")
    language = SYSTEM_LANGUAGES.get(locale, 1) if isinstance(locale, str) else 1
    command = ([sys.executable, "--run-backend"] if FROZEN else
               [sys.executable, str(ROOT / "order1886.py")])
    command += ["--game-dir", values["game_dir"], "--state-dir", str(state),
                "--display-mode", values["display_mode"],
                "--vsync", str(int(values["vsync"])),
                 "--show-fps", str(int(values["show_fps"])),
                 "--presentation-filter", values.get("presentation_filter", "fsr1"),
                 "--frame-rate", str(values.get("frame_rate", 30)),
                "--aspect-ratio", values.get("aspect_ratio", "original"),
                "--mouse-look", str(int(values.get("mouse_look", True))),
                "--mouse-sensitivity", str(values.get("mouse_sensitivity", 100)),
                "--mouse-invert-y", str(int(values.get("mouse_invert_y", False))),
                "--system-language", str(language)]
    command += ["--readbacks", values.get("readbacks", "relaxed")]
    # The presentation cap is a launcher setting; without this it never reached the backend
    # and the value shown in the UI was not the one applied.
    command += ["--fps-cap", str(values.get("fps_cap", 120))]
    command += ["--performance-capture", str(int(values.get("performance_capture", False)))]
    from order1886 import GRAPHICS_DEFAULTS
    for key, default in GRAPHICS_DEFAULTS.items():
        value = values.get(key, default)
        command += ["--" + key.replace("_", "-"), str(int(value)) if type(value) is bool else str(value)]
    # Live runtime switches stay off the command line unless the player asked for them.
    if values.get("htile_unqualified"):
        command += ["--htile"]
    if values.get("in_game_menu"):
        command += ["--in-game-menu"]
    if values.get("synchronous_recording"):
        command += ["--synchronous-recording"]
    if values.get("texture_update_locking"):
        command += ["--texture-update-locking"]
    for kind in ('keyboard', 'controller'):
        mapping = values.get(kind + '_bindings', {})
        inputs.validate(mapping, kind)
        command += ['--' + kind + '-bindings', json.dumps(mapping, ensure_ascii=False)]
    if values.get("runtime"):
        command += ["--runtime", values["runtime"]]
    # Catalogued recipes the player selected travel to preparation, where each one is
    # validated against the build identity and its expected bytes before any edit.
    # A post effect the player turned off travels to preparation, which patches a prepared copy.
    from order1886 import post_effects
    disabled = [key for key in post_effects.EFFECTS if values.get(key, True) is False]
    if disabled:
        command += ["--disable-effects", ",".join(disabled)]
    selected = values.get("selected_patches") or []
    if selected:
        command += ["--patches", ",".join(str(name) for name in selected)]
    if mode == "play":
        from order1886 import mods
        enabled, order = values.get("mods_enabled", False), values.get("mod_order", [])
        mod_root = mods.resolve_root(values.get("mods_dir", ""), ROOT)
        mods.validate_config(mod_root, enabled, order)
        command += ["--mods-dir", str(mod_root), "--mods-enabled", str(int(enabled)),
                    "--mods-order", json.dumps(order, ensure_ascii=False)]
    if mode == "verify":
        command += ["--check-imports"]
    if stop_file is not None:
        command += ["--stop-file", str(stop_file)]
    return command


class EventSink(Protocol):
    def put(self, event: tuple) -> None: ...


def session_worker(command: list[str], logfile: Path, events: EventSink,
                   cancelled: threading.Event, stop_file: Path,
                   mode: str, cwd: Path = ROOT) -> None:
    """Run one backend off the UI thread; record startup failures and stop races."""
    code = 1
    try:
        with logfile.open("w", encoding="utf-8", buffering=1) as log:
            def record(line):
                log.seek(0, os.SEEK_END)
                log.write(line)
                log.flush()
                events.put(("line", line))
            record(f"Launcher command: {subprocess.list2cmdline(command)}\n")
            record(f"Working directory: {cwd}\n")
            if cancelled.is_set():
                record("Session stopped before backend startup.\n")
                code = 130
                return
            try:
                with logfile.open("rb") as reader:
                    reader.seek(log.tell())
                    decoder = io.IncrementalNewlineDecoder(
                        codecs.getincrementaldecoder("utf-8")("replace"), True)
                    pending = ""

                    def relay(final=False):
                        nonlocal pending
                        pending += decoder.decode(reader.read(), final=final)
                        lines = pending.splitlines(keepends=True)
                        pending = ""
                        for line in lines:
                            if final or line.endswith("\n"):
                                events.put(("line", line))
                            else:
                                pending = line

                    # A real file survives console detachment and is already the session evidence.
                    with subprocess.Popen(
                        command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    ) as process:
                        events.put(("started", process.pid))
                        if cancelled.is_set():
                            stop_file.touch()
                        while process.poll() is None:
                            relay()
                            time.sleep(0.05)
                        code = process.wait()
                        relay(final=True)
            except Exception as exc:
                record(f"Could not start session: {exc}\n")
            record(f"Backend exit code: {code}\n")
    except OSError as exc:
        events.put(("line", f"Cannot write session log: {exc}\n"))
    finally:
        try:
            stop_file.unlink(missing_ok=True)
        except OSError:
            pass
        events.put(("done", (code, mode, cancelled.is_set())))


def load_launch_settings(state: Path, saved: dict | None = None) -> dict:
    """Use one set of defaults for the desktop and direct-play entry points."""
    import order1886
    if saved is None:
        saved = read_settings(state / "settings.json")
    values = {
        **saved,
        "game_dir": str(saved.get("game_dir", order1886.default_game_dir())),
        "runtime": str(saved.get("runtime", "")),
        "display_mode": saved.get("display_mode", "borderless"),
        "vsync": bool(saved.get("vsync", True)),
        "show_fps": bool(saved.get("show_fps", True)),
        "presentation_filter": saved.get("presentation_filter", "fsr1"),
        "readbacks": saved.get("readbacks", "relaxed"),
        "performance_capture": saved.get("performance_capture", False),
        "frame_rate": saved.get("frame_rate", 30),
        "aspect_ratio": saved.get("aspect_ratio", "original"),
        "mouse_look": bool(saved.get("mouse_look", True)),
        "mouse_sensitivity": saved.get("mouse_sensitivity", 100),
        "mouse_invert_y": bool(saved.get("mouse_invert_y", False)),
        "ui_language": saved.get("ui_language", "en"),
        "htile_unqualified": bool(saved.get("htile_unqualified", False)),
        "synchronous_recording": bool(saved.get("synchronous_recording", False)),
        "texture_update_locking": bool(saved.get("texture_update_locking", False)),
        "fps_cap": saved.get("fps_cap", 120),
        "in_game_menu": bool(saved.get("in_game_menu", False)),
        "automatic_updates": bool(saved.get("automatic_updates", False)),
        "update_channel": saved.get("update_channel", "preview"),
        "mods_dir": saved.get("mods_dir", ""),
        "mods_enabled": saved.get("mods_enabled", False),
        "mod_order": saved.get("mod_order", []),
        "selected_patches": saved.get("selected_patches", []),
        **{key: saved.get(key, default) for key, default in order1886.GRAPHICS_DEFAULTS.items()},
        **{key: bool(saved.get(key, True)) for key in order1886.post_effects.EFFECTS},
    }
    for key, allowed, default in (
        ("display_mode", ("windowed", "borderless", "fullscreen"), "borderless"),
        ("presentation_filter", ("linear", "fsr1"), "fsr1"),
        ("aspect_ratio", ("original", "16:9"), "original"),
    ):
        if values[key] not in allowed:
            values[key] = default
    # A saved value the backend cannot honour is a launch-blocking error, not something to rewrite
    # silently: a player who once chose 90 FPS would otherwise be told nothing and run at 30.
    if type(values["frame_rate"]) is not int or values["frame_rate"] not in order1886.timing.RATES:
        raise ValueError(
            f"Saved game frame rate {values['frame_rate']!r} is not supported: the backend accepts 30, "
            "60 or 90 FPS, or Unlocked (#14).")
    if type(values["mouse_sensitivity"]) is not int or not 10 <= values["mouse_sensitivity"] <= 500:
        values["mouse_sensitivity"] = 100
    return values


def validate_launch_game(game: Path, values: dict) -> None:
    """Use the backend's exact patch guards before creating a play session."""
    import order1886
    custom = any(values.get(kind + '_bindings', {}) for kind in ('keyboard', 'controller'))
    runtime = order1886.find_runtime(values.get('runtime') or None) if custom else None
    order1886.validate_input_settings(runtime, values)
    order1886.mods.validate_config(order1886.mods.resolve_root(values.get("mods_dir", ""), ROOT), values.get("mods_enabled", False),
                                  values.get("mod_order", []))
    game = (game if game.is_absolute() else ROOT / game).resolve()
    metadata = order1886.inspect_game(game)
    try:
        order1886.timing.validate_source(game / "eboot.bin", values.get("frame_rate", 30), metadata)
        order1886.display.validate_source(game / "eboot.bin", values.get("aspect_ratio", "original"), metadata)
        order1886.post_effects.validate_source(
            game / "eboot.bin", [key for key in order1886.post_effects.EFFECTS if values.get(key, True) is False],
            metadata)
    except ValueError as exc:
        raise ValueError(translate(
            "Selected settings do not match this executable. Detected APP_VER {app_ver}, VERSION {version}.\n\n"
            "{error}\n\nSelect 30 FPS and Original cinematic aspect to use the unpatched profile. "
            "Fullscreen is a separate display setting. Gameplay compatibility still requires verification.",
            values.get("ui_language", "en"), app_ver=metadata.get("APP_VER", "unknown"),
            version=metadata.get("VERSION", "unknown"), error=exc)) from exc


def create_desktop_shortcut(installation: Path = ROOT, desktop: Path | None = None) -> Path:
    if os.name != "nt":
        raise ValueError("Desktop shortcuts currently require Windows.")
    installation = installation.resolve()
    target = installation / "Play The Order 1886.exe"
    if not target.is_file():
        raise ValueError("Install or build the portable package containing Play The Order 1886.exe first.")
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    if not powershell.is_file():
        raise OSError("Windows PowerShell is unavailable; the desktop shortcut could not be created.")
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    desktop_expression = quote(desktop.resolve()) if desktop else "[Environment]::GetFolderPath('Desktop')"
    if desktop:
        desktop.mkdir(parents=True, exist_ok=True)
    script = (
        "$ErrorActionPreference='Stop'\n"
        "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)\n"
        f"$desktop={desktop_expression}\n"
        "if (-not $desktop) { throw 'Windows did not provide a Desktop folder.' }\n"
        "$path=Join-Path $desktop 'Play The Order 1886.lnk'\n"
        "$link=(New-Object -ComObject WScript.Shell).CreateShortcut($path)\n"
        f"$link.TargetPath={quote(target)}\n"
        f"$link.WorkingDirectory={quote(installation)}\n"
        f"$link.IconLocation={quote(str(installation / 'The Order 1886.exe') + ',0')}\n"
        "$link.Arguments=''\n$link.Save()\n[Console]::WriteLine($path)\n"
    )
    result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-EncodedCommand",
                             base64.b64encode(script.encode("utf-16le")).decode("ascii")],
                            check=True, capture_output=True, encoding="utf-8", timeout=30,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    shortcut = Path(result.stdout.strip())
    if not shortcut.is_file():
        raise OSError("Windows did not create the requested shortcut.")
    return shortcut
