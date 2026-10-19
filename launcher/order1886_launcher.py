#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""The Order: 1886 desktop launcher. Its settings and logs are title-isolated."""
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
GOLD, PAPER, MUTED, BLACK = "#d4bd75", "#e9e5d8", "#a8a497", "#0b0b0a"
DISPLAY = {"Windowed": "windowed", "Borderless": "borderless", "Fullscreen": "fullscreen"}
UPSCALING = {"FSR 1": "fsr1", "Linear": "linear"}
FRAME_RATE = {"30 FPS": 30, "60 FPS (experimental)": 60}
ASPECT_RATIO = {"Full screen 16:9 (experimental)": "16:9", "Original cinematic aspect": "original"}
# Page order adapted from mateussmeneses/theorder1886-port, GPL-2.0-or-later.
# Reference: 7822ee56c2169f15ecde5d80f39e96143a252464, launcher/port_launcher_win.py.
PAGES = ("home", "graphics", "performance", "game", "advanced")
PAGE_TITLES = dict(zip(PAGES, ("Home", "Graphics", "Performance", "Game", "Advanced")))
SETTINGS_KEYS = ("game_dir", "runtime", "display_mode", "vsync", "show_fps",
                 "presentation_filter", "frame_rate", "aspect_ratio", "mouse_look", "readbacks",
                 "mouse_sensitivity", "mouse_invert_y", "ui_language", "mods_dir", "mods_enabled")


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
    from order1886 import SYSTEM_LANGUAGES
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
    if values.get("runtime"):
        command += ["--runtime", values["runtime"]]
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


def attach_stdio() -> None:
    """Recover redirected windowed-backend handles without owning borrowed/shared handles."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        import msvcrt
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetStdHandle.argtypes = [wintypes.DWORD]
        kernel.GetStdHandle.restype = wintypes.HANDLE
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.DuplicateHandle.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
            ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.DuplicateHandle.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        process = kernel.GetCurrentProcess()
        for name, code in (("stdout", -11), ("stderr", -12)):
            if getattr(sys, name) is None:
                owned = wintypes.HANDLE()
                try:
                    handle = kernel.GetStdHandle(code & 0xffffffff)
                    if not kernel.DuplicateHandle(process, handle, process, ctypes.byref(owned), 0, False, 2):
                        raise ctypes.WinError(ctypes.get_last_error())
                    fd = msvcrt.open_osfhandle(owned.value, os.O_WRONLY | os.O_BINARY)
                    owned = wintypes.HANDLE()  # The descriptor now owns the duplicate.
                    try:
                        stream = open(fd, "w", encoding="utf-8", errors="replace", buffering=1)
                    except BaseException:
                        os.close(fd)
                        raise
                except (OSError, TypeError, OverflowError):
                    if owned.value:
                        kernel.CloseHandle(owned)
                    # Backend status writes have a durable state-log fallback when no handle exists.
                    stream = None
                setattr(sys, name, stream)


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
        "frame_rate": saved.get("frame_rate", 30),
        "aspect_ratio": saved.get("aspect_ratio", "original"),
        "mouse_look": bool(saved.get("mouse_look", True)),
        "mouse_sensitivity": saved.get("mouse_sensitivity", 100),
        "mouse_invert_y": bool(saved.get("mouse_invert_y", False)),
        "ui_language": saved.get("ui_language", "en"),
        "mods_dir": saved.get("mods_dir", ""),
        "mods_enabled": saved.get("mods_enabled", False),
        "mod_order": saved.get("mod_order", []),
    }
    for key, allowed, default in (
        ("display_mode", ("windowed", "borderless", "fullscreen"), "borderless"),
        ("presentation_filter", ("linear", "fsr1"), "fsr1"),
        ("aspect_ratio", ("original", "16:9"), "original"),
    ):
        if values[key] not in allowed:
            values[key] = default
    if type(values["frame_rate"]) is not int or values["frame_rate"] not in (30, 60):
        values["frame_rate"] = 30
    if type(values["mouse_sensitivity"]) is not int or not 10 <= values["mouse_sensitivity"] <= 500:
        values["mouse_sensitivity"] = 100
    return values


class _QuickPlayEvents:
    """The session log stays on disk; direct play only retains recent error context."""
    def __init__(self):
        self.code = 1
        self.tail = deque(maxlen=3)

    def put(self, event: tuple) -> None:
        kind, value = event
        if kind == "done":
            self.code, _mode, _cancelled = value
        elif kind == "line":
            self.tail.append(value)


def validate_launch_game(game: Path, values: dict) -> None:
    """Use the backend's exact patch guards before creating a play session."""
    import order1886
    order1886.mods.validate_config(order1886.mods.resolve_root(values.get("mods_dir", ""), ROOT), values.get("mods_enabled", False),
                                  values.get("mod_order", []))
    game = (game if game.is_absolute() else ROOT / game).resolve()
    metadata = order1886.inspect_game(game)
    try:
        order1886.timing.validate_source(game / "eboot.bin", values.get("frame_rate", 30), metadata)
        order1886.display.validate_source(game / "eboot.bin", values.get("aspect_ratio", "original"), metadata)
    except ValueError as exc:
        raise ValueError(translate(
            "Selected settings do not match this executable. Detected APP_VER {app_ver}, VERSION {version}.\n\n"
            "{error}\n\nSelect 30 FPS and Original cinematic aspect to use the unpatched profile. "
            "Fullscreen is a separate display setting. Gameplay compatibility still requires verification.",
            values.get("ui_language", "en"), app_ver=metadata.get("APP_VER", "unknown"),
            version=metadata.get("VERSION", "unknown"), error=exc)) from exc


def run_saved_game(state: Path, on_error=None) -> int | None:
    """None opens setup; configured installs use exactly the GUI Play worker."""
    import order1886
    state = state.resolve()
    if not (state / "settings.json").is_file():
        return None
    saved = read_settings(state / "settings.json")
    if not saved:
        return None
    values = load_launch_settings(state, saved)
    for key in ("display_mode", "presentation_filter", "aspect_ratio", "frame_rate",
                "mouse_sensitivity", "mouse_look", "mouse_invert_y", "vsync", "show_fps"):
        if key in saved and (type(saved[key]) is not type(values[key]) or saved[key] != values[key]):
            if on_error:
                on_error(translate("Saved setting '{key}' is unsupported. Review it in the launcher and save your settings before using direct play.", values["ui_language"], key=key))
            return None
    try:
        game = Path(values["game_dir"])
        runtime = Path(values["runtime"]) if values["runtime"] else None
        game = (game if game.is_absolute() else ROOT / game).resolve()
        if state == game or game in state.parents:
            return None
        validate_launch_game(game, values)
        if runtime and not runtime.is_absolute():
            runtime = ROOT / runtime
        if order1886.find_runtime(runtime) is None:
            return None
    except (OSError, ValueError) as exc:
        if on_error:
            on_error(str(exc))
        return None
    token = uuid.uuid4().hex
    stop_file = state / f"session-stop-{token}"
    logfile = state / f"launcher-{time.strftime('%Y%m%d-%H%M%S')}-{token[:8]}.log"
    events = _QuickPlayEvents()
    session_worker(backend_command(values, state=state, stop_file=stop_file), logfile,
                   events, threading.Event(), stop_file, "play", ROOT)
    code = events.code
    if code not in (0, 130) and on_error:
        details = "".join(events.tail).strip()[-1200:]
        on_error(translate("The game exited with code {code}.\n{details}\n\nOpen the launcher to check your game and runtime settings.\nLog: {logfile}", values["ui_language"], code=code, details=details, logfile=logfile))
    return code


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


class Launcher:
    def __init__(self, root, state: Path = STATE):
        import tkinter as tk
        from PIL import Image, ImageTk
        import order1886

        self.tk, self.root, self.state = tk, root, state
        self.Image, self.ImageTk = Image, ImageTk
        self.events = queue.Queue()
        self.process = None
        self.session_cancel = threading.Event()
        self.session_thread = None
        self.stop_file = None
        self.closing = False
        self.session_started = 0
        self.session_mode = None
        self.busy = False
        self.log_window = None
        self.log_text = None
        self.log_buffer = []
        self.settings_frame = None
        self.background_photo = None
        self.resize_timer = None
        self.values = load_launch_settings(state)
        language = self.values["ui_language"]
        self.language = language if isinstance(language, str) and language in LANGUAGES else "en"
        root.title(self.tr("The Order: 1886"))
        root.configure(bg=BLACK)
        root.geometry("1160x760")
        root.minsize(940, 620)
        try:
            root.iconbitmap(str(ASSETS / ("order1886.ico" if FROZEN else "native/order1886.ico")))
        except tk.TclError:
            pass
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(root, bg=BLACK, highlightthickness=0, takefocus=True)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.build_home()
        self.backdrop = None
        self.icon_photo = None
        self.load_artwork()
        self.canvas.bind("<Configure>", self.resize)
        root.bind("<Return>", self.activate)
        root.bind("<Escape>", self.back)
        self.status = "Experimental compatibility build"
        self.detail = "Gameplay and performance are not yet verified."
        self.refresh_status()
        self.draw()
        root.after(100, self.poll)

    def tr(self, text, **values):
        return translate(text, getattr(self, "language", "en"), **values)

    @property
    def text_anchor(self):
        return "e" if getattr(self, "language", "en") == "ar" else "w"

    @property
    def text_justify(self):
        return "right" if getattr(self, "language", "en") == "ar" else "left"

    def build_home(self):
        from tkinter import ttk
        tk = self.tk
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Order.TCombobox", fieldbackground="#171817", background="#20201c",
                        foreground=PAPER, arrowcolor=PAPER, bordercolor="#64635b",
                        lightcolor="#64635b", darkcolor="#64635b", padding=(12, 9),
                        font=("Segoe UI", 11))
        style.map("Order.TCombobox", fieldbackground=[("readonly", "#171817")],
                  foreground=[("disabled", MUTED), ("readonly", PAPER)],
                  bordercolor=[("focus", GOLD)])
        self.root.option_add("*TCombobox*Listbox.background", "#20201c")
        self.root.option_add("*TCombobox*Listbox.foreground", PAPER)
        self.root.option_add("*TCombobox*Listbox.selectBackground", GOLD)
        self.root.option_add("*TCombobox*Listbox.selectForeground", BLACK)
        self.root.option_add("*TCombobox*Listbox.font", ("Segoe UI", 11))
        self.navigation = tk.Frame(self.canvas, bg=BLACK)
        self.navigation.place(relx=.965, y=30, anchor="ne")
        self.nav_buttons = []
        for index, (label, command) in enumerate((("Settings", self.settings),
                ("Verify files", lambda: self.run("verify")), ("View logs", self.show_logs))):
            if index:
                tk.Frame(self.navigation, width=1, height=18, bg="#514932").pack(side="left", padx=8)
            button = self.button(self.navigation, label, command)
            button.configure(bg=BLACK, highlightbackground=BLACK, padx=10, pady=6)
            button.pack(side="left")
            self.nav_buttons.append(button)
        self.console = tk.Frame(self.root, bg="#141513", padx=42, pady=20)
        self.console.grid(row=1, column=0, sticky="ew")
        self.console.columnconfigure(0, weight=1)
        folder = tk.Frame(self.console, bg="#141513")
        folder.grid(row=0, column=0, sticky="ew")
        folder.columnconfigure(1, weight=1)
        tk.Label(folder, text=self.tr("Game folder"), bg="#141513", fg=PAPER,
                 font=("Segoe UI", 11)).grid(row=0, column=0, padx=(0, 22))
        self.home_fields = {"game_dir": tk.StringVar()}
        self.game_entry = tk.Entry(folder, textvariable=self.home_fields["game_dir"],
            bg="#171817", fg=PAPER, insertbackground=GOLD, selectbackground=GOLD,
            selectforeground=BLACK, relief="flat", highlightthickness=1,
            highlightbackground="#64635b", highlightcolor=GOLD, font=("Segoe UI", 11))
        self.game_entry.grid(row=0, column=1, sticky="ew", ipady=9)
        self.game_entry.bind("<Return>", lambda e: (self.commit_home(), "break")[1])
        self.change_button = self.button(folder, "Change", self.change_folder)
        self.change_button.grid(row=0, column=2, padx=(10, 18))
        self.readiness = tk.Label(folder, bg="#141513", fg=MUTED,
                                  font=("Segoe UI", 10), anchor="w", width=25)
        self.readiness_icon = tk.Canvas(folder, width=22, height=22, bg="#141513", highlightthickness=0)
        self.readiness_icon.grid(row=0, column=3, padx=(0, 8))
        self.readiness.grid(row=0, column=4, sticky="w")
        tk.Frame(self.console, bg="#34352f", height=1).grid(row=1, column=0, sticky="ew", pady=17)
        controls = tk.Frame(self.console, bg="#141513")
        controls.grid(row=2, column=0, sticky="ew")
        self.quick_controls = []
        for index, (key, label, choices) in enumerate((("display_mode", "Display", DISPLAY),
                ("presentation_filter", "Upscaling", UPSCALING), ("frame_rate", "Frame rate", FRAME_RATE))):
            controls.columnconfigure(index, weight=1, uniform="essential")
            group = tk.Frame(controls, bg="#141513")
            group.grid(row=0, column=index, sticky="nsew", padx=(0, 24))
            tk.Label(group, text=self.tr(label), fg=PAPER, bg="#141513",
                     font=("Segoe UI", 10), anchor="w").pack(fill="x", pady=(0, 6))
            variable = self.home_fields[key] = tk.StringVar()
            combo = ttk.Combobox(group, textvariable=variable, values=[self.tr(label) for label in choices],
                                 state="readonly", style="Order.TCombobox", width=1,
                                 font=("Segoe UI", 11), justify=self.text_justify)
            combo.pack(fill="x")
            combo.bind("<<ComboboxSelected>>", lambda e: self.commit_home())
            self.quick_controls.append(combo)
        controls.columnconfigure(3, weight=1, uniform="essential")
        self.play_button = self.button(controls, "Play", self.play_or_stop)
        self.play_button.configure(bg=GOLD, fg=BLACK, activebackground="#e5cf8c",
                                   activeforeground=BLACK, font=("Segoe UI", 22),
                                   highlightbackground=GOLD, pady=8)
        self.play_button.grid(row=0, column=3, sticky="nsew")
        self.play_texture = None
        try:
            with self.Image.open(ASSETS / "play-brass.png") as texture:
                self.play_texture = texture.convert("RGB")
        except OSError:
            pass
        self.play_surface_size = None
        notice = tk.Frame(controls, bg="#141513")
        notice.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(16, 0))
        warning_icon = tk.Canvas(notice, width=24, height=22, bg="#141513", highlightthickness=0)
        warning_icon.pack(side="left", anchor="n", padx=(0, 9))
        warning_icon.create_polygon(11, 1, 21, 20, 1, 20, fill=GOLD, outline=GOLD)
        warning_icon.create_line(11, 6, 11, 12, fill=BLACK, width=2)
        warning_icon.create_oval(10, 15, 12, 17, fill=BLACK, outline=BLACK)
        self.warning = tk.Label(notice, text=self.tr("Experimental runtime. Gameplay is not yet verified."),
            fg=GOLD, bg="#141513", font=("Segoe UI", 10), anchor="w", justify=self.text_justify)
        self.warning.pack(side="left", fill="x", expand=True)
        self.play_hint = tk.Label(controls, text=self.tr("Enter to play"), fg=MUTED, bg="#141513",
                                 font=("Segoe UI", 9))
        self.play_hint.grid(row=1, column=3, pady=(10, 0))
        self.sync_home()

    def sync_home(self):
        self.home_fields["game_dir"].set(self.values["game_dir"])
        for key, choices in (("display_mode", DISPLAY), ("presentation_filter", UPSCALING),
                             ("frame_rate", FRAME_RATE)):
            self.home_fields[key].set(next(self.tr(label) for label, value in choices.items()
                                          if value == self.values[key]))

    def commit_home(self):
        from tkinter import messagebox
        values = dict(self.values, game_dir=self.home_fields["game_dir"].get().strip())
        if not values["game_dir"]:
            messagebox.showerror(self.tr("Choose a game folder"), self.tr("Select the extracted CUSA00076 folder before continuing."), parent=self.root)
            return False
        for key, choices in (("display_mode", DISPLAY), ("presentation_filter", UPSCALING),
                             ("frame_rate", FRAME_RATE)):
            values[key] = next(value for label, value in choices.items()
                               if self.tr(label) == self.home_fields[key].get())
        try:
            save_settings(self.state / "settings.json", values)
        except (OSError, ValueError) as exc:
            messagebox.showerror(self.tr("Settings could not be saved"), self.tr(str(exc)), parent=self.root)
            self.sync_home()
            return False
        changed_folder = values["game_dir"] != self.values["game_dir"]
        self.values = values
        if changed_folder:
            self.load_artwork()
        if not self.busy:
            self.refresh_status()
        self.draw()
        return True

    def change_folder(self):
        from tkinter import filedialog
        value = filedialog.askdirectory(parent=self.root, title=self.tr("Choose extracted CUSA00076 folder"),
                                        initialdir=self.values["game_dir"])
        if value:
            self.home_fields["game_dir"].set(value)
            self.commit_home()

    def play_or_stop(self):
        if self.busy:
            self.stop()
        else:
            self.run("play")

    def load_artwork(self):
        """Use the supplied wallpaper; original game files remain read-only."""
        artwork = Path(self.values["game_dir"]) / "sce_sys"
        self.backdrop = None
        self.artwork_size = None
        for path in (ASSETS / "launcher-art.jpg", ASSETS / "launcher-art.png",
                     artwork / "pic0.png", ASSETS / "background.png"):
            try:
                with self.Image.open(path) as image:
                    self.backdrop = image.convert("RGB")
                break
            except OSError:
                continue
        self.brand_logo, self.logo_photo, self.logo_size = None, None, None
        try:
            with self.Image.open(ASSETS / "logo-horizontal.png") as logo:
                rgba = logo.convert("RGBA")
                self.brand_logo = rgba.crop(rgba.getbbox())
        except OSError:
            pass
        for path in (ASSETS / "app-icon.png", artwork / "icon0.png"):
            try:
                with self.Image.open(path) as icon:
                    self.icon_photo = self.ImageTk.PhotoImage(icon.convert("RGBA"))
                self.root.iconphoto(True, self.icon_photo)
                break
            except (OSError, self.tk.TclError):
                continue

    def refresh_status(self):
        import order1886
        try:
            order1886.inspect_game(Path(self.values["game_dir"]))
        except (OSError, ValueError) as exc:
            self.status = "Game files need attention"
            self.detail = str(exc)
            return
        try:
            runtime = order1886.find_runtime(self.values["runtime"] or None)
            self.status = "CUSA00076  /  Game files found"
            self.detail = ("Experimental runtime. Gameplay is not yet verified." if runtime else
                           "Runtime missing. Install a complete package or select one in Settings.")
        except (OSError, ValueError) as exc:
            self.status = "Runtime needs attention"
            self.detail = str(exc)

    def resize(self, event=None):
        if self.resize_timer:
            self.root.after_cancel(self.resize_timer)
        self.resize_timer = self.root.after(60, self.draw)

    def draw(self):
        self.resize_timer = None
        c = self.canvas
        c.delete("all")
        w, h = max(c.winfo_width(), 940), max(c.winfo_height(), 260)
        if self.backdrop:
            from PIL import ImageOps
            if getattr(self, "artwork_size", None) != (w, h):
                display = ImageOps.fit(self.backdrop, (w, h),
                                       method=self.Image.Resampling.LANCZOS, centering=(.5, .5))
                self.background_photo = self.ImageTk.PhotoImage(display)
                self.artwork_size = (w, h)
            c.create_image(0, 0, image=self.background_photo, anchor="nw")
        from tkinter import font as tkfont
        if self.brand_logo is not None:
            from PIL import ImageOps
            logo_size = (int(w * .72), int(h * .22))
            if self.logo_size != logo_size:
                logo = ImageOps.contain(self.brand_logo, logo_size, self.Image.Resampling.LANCZOS)
                self.logo_photo = self.ImageTk.PhotoImage(logo)
                self.logo_size = logo_size
            c.create_image(w * .037, h * .07, image=self.logo_photo, anchor="nw")
        else:
            c.create_text(w * .037, h * .09, text=self.tr("The Order: 1886"), font=("Georgia", 32),
                          fill=GOLD, anchor="nw")
        self.readiness.configure(text=self.tr(self.status.replace("CUSA00076  /  ", "")),
                                 fg="#aec58f" if "Game files found" in self.status else MUTED,
                                 wraplength=210, justify=self.text_justify)
        self.readiness_icon.delete("all")
        if "Game files found" in self.status:
            self.readiness_icon.create_oval(1, 1, 21, 21, fill="#aec58f", outline="")
            self.readiness_icon.create_line(6, 11, 10, 15, 16, 7, fill=BLACK, width=2)
        self.play_button.configure(text=self.tr("Stopping…" if self.busy and self.session_cancel.is_set()
                                   else "Stop session" if self.busy else "Play"),
                                   font=("Segoe UI", 15 if self.busy else 22), disabledforeground=BLACK,
                                   state="disabled" if self.busy and self.session_cancel.is_set() else "normal")
        surface_size = (self.play_button.winfo_width(), self.play_button.winfo_height(), self.busy)
        if self.play_texture and min(surface_size[:2]) > 1 and self.play_surface_size != surface_size:
            from PIL import ImageDraw, ImageOps
            bw, bh, busy = surface_size
            surface = self.Image.new("RGB", (bw, bh))
            tw, th = self.play_texture.size
            for y in range(0, bh, th):
                for x in range(0, bw, tw):
                    tile = ImageOps.mirror(self.play_texture) if (x // tw) % 2 else self.play_texture
                    surface.paste(ImageOps.flip(tile) if (y // th) % 2 else tile, (x, y))
            if not busy:
                label_width = tkfont.Font(font=self.play_button.cget("font")).measure(self.tr("Play"))
                x, y = bw // 2 + label_width // 2 + 14, bh // 2
                ImageDraw.Draw(surface).polygon(((x, y - 8), (x, y + 8), (x + 12, y)), fill=BLACK)
            self.play_surface = self.ImageTk.PhotoImage(surface)
            self.play_button.configure(image=self.play_surface, compound="center", width=1, height=1)
            self.play_surface_size = surface_size
        state = "disabled" if self.busy or self.settings_frame else "normal"
        self.game_entry.configure(state=state)
        self.change_button.configure(state=state)
        for combo in self.quick_controls:
            combo.configure(state="disabled" if self.busy or self.settings_frame else "readonly")
        for button in self.nav_buttons[:2]:
            button.configure(state=state)
        warning = self.tr("Experimental runtime. Gameplay is not yet verified.")
        if self.values["frame_rate"] == 60:
            import order1886
            warning += "\n" + self.tr(order1886.timing.WARNING)
        if self.detail != "Experimental runtime. Gameplay is not yet verified.":
            warning += "\n" + self.tr(self.detail)
        self.warning.configure(text=self.tr(warning), wraplength=max(480, int((w - 84) * .73) - 36))
        self.play_hint.configure(text=self.tr("View logs for progress" if self.busy else "Enter to play"))

    def activate(self, event=None):
        if event and event.widget.winfo_class() in ("Button", "TButton"):
            event.widget.invoke()
            return "break"
        if not self.settings_frame and (event is None or event.widget in (self.root, self.canvas)):
            self.play_or_stop()
            return "break"

    def back(self, event=None):
        if self.settings_frame:
            self.settings_frame.destroy()
            self.settings_frame = None
            self.draw()
            self.nav_buttons[0].focus_set()

    def button(self, parent, text, command):
        return self.tk.Button(parent, text=self.tr(text), command=command, bg="#25241f", fg=PAPER,
                              activebackground="#3a3525", activeforeground=GOLD,
                              relief="flat", bd=0, padx=16, pady=9,
                              highlightthickness=1, highlightbackground="#514932",
                              highlightcolor=GOLD, font=("Segoe UI", 10), cursor="hand2")

    def settings(self):
        from tkinter import filedialog, messagebox
        if self.settings_frame:
            return
        if self.busy or not self.commit_home():
            return
        tk = self.tk
        container = self.settings_frame = tk.Frame(self.root, bg=BLACK)
        container.place(relx=1, y=0, anchor="ne", width=560, relheight=1)
        self.draw()
        scrollbar = tk.Scrollbar(container, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        scroller = tk.Canvas(container, bg=BLACK, highlightthickness=0, yscrollcommand=scrollbar.set)
        scroller.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=scroller.yview)
        frame = tk.Frame(scroller, bg=BLACK, padx=35, pady=30)
        window = scroller.create_window(0, 0, anchor="nw", window=frame)
        frame.bind("<Configure>", lambda e: scroller.configure(scrollregion=scroller.bbox("all")))
        scroller.bind("<Configure>", lambda e: scroller.itemconfigure(window, width=e.width))
        def wheel(event):
            if self.settings_frame and scroller.winfo_exists():
                scroller.yview_scroll(-int(event.delta / 120), "units")
        def focus_visible(event):
            if self.settings_frame and scroller.winfo_exists() and str(event.widget).startswith(str(frame) + "."):
                top = event.widget.winfo_rooty() - frame.winfo_rooty()
                visible = scroller.canvasy(0)
                if top < visible or top + event.widget.winfo_height() > visible + scroller.winfo_height():
                    scroller.yview_moveto(max(0, top - 20) / max(1, frame.winfo_height()))
        self.root.bind("<MouseWheel>", wheel)
        self.root.bind("<FocusIn>", focus_visible)
        tk.Label(frame, text=self.tr("SETTINGS"), fg=GOLD, bg=BLACK, font=("Georgia", 21)).pack(anchor=self.text_anchor, pady=(15, 25))
        fields = {}
        for key, label, is_folder in (("game_dir", "Game folder", True),
                            ("runtime", "Runtime executable (optional)", False)):
            tk.Label(frame, text=self.tr(label), fg=PAPER, bg=BLACK, font=("Segoe UI", 10)).pack(anchor=self.text_anchor, pady=(8, 7))
            row = tk.Frame(frame, bg=BLACK)
            row.pack(fill="x")
            variable = fields[key] = tk.StringVar(value=self.values[key])
            entry = tk.Entry(row, textvariable=variable, bg="#20201c", fg=PAPER, insertbackground=GOLD,
                             relief="flat", font=("Segoe UI", 10), highlightthickness=1,
                             highlightbackground="#514932", highlightcolor=GOLD)
            entry.pack(side="left", fill="x", expand=True, ipady=10)
            def browse(v=variable, folder=is_folder):
                value = (filedialog.askdirectory(parent=self.root, title=self.tr("Choose extracted CUSA00076 folder")) if folder else
                         filedialog.askopenfilename(parent=self.root, title=self.tr("Choose The Order: 1886 runtime"), filetypes=[(self.tr("Order runtime"), "order1886-runtime.exe"), (self.tr("Executables"), "*.exe")]))
                if value:
                    v.set(value)
            self.button(row, "Browse", browse).pack(side="right", padx=(8, 0))
        tk.Label(frame, text=self.tr("Display mode"), fg=PAPER, bg=BLACK, font=("Segoe UI", 10)).pack(anchor=self.text_anchor, pady=(23, 8))
        display = tk.StringVar(value=self.values["display_mode"])
        for mode in ("windowed", "borderless", "fullscreen"):
            tk.Radiobutton(frame, text=self.tr(mode.capitalize()), variable=display, value=mode,
                           bg=BLACK, fg=PAPER, selectcolor="#26251f", activebackground=BLACK,
                           activeforeground=GOLD, font=("Segoe UI", 10)).pack(anchor=self.text_anchor, pady=2)
        tk.Label(frame, text=self.tr("Aspect ratio"), fg=PAPER, bg=BLACK,
                 font=("Segoe UI", 10)).pack(anchor=self.text_anchor, pady=(18, 8))
        aspect = tk.StringVar(value=self.values["aspect_ratio"])
        for label, value in ASPECT_RATIO.items():
            tk.Radiobutton(frame, text=self.tr(label), variable=aspect, value=value,
                           bg=BLACK, fg=PAPER, selectcolor="#26251f", activebackground=BLACK,
                           activeforeground=GOLD, font=("Segoe UI", 10)).pack(anchor=self.text_anchor, pady=2)
        tk.Label(frame, text=self.tr("Aspect changes apply after restarting the game."), fg=MUTED, bg=BLACK,
                 font=("Segoe UI", 9)).pack(anchor=self.text_anchor, pady=(5, 0))
        tk.Label(frame, text=self.tr("Output scaling"), fg=PAPER, bg=BLACK,
                 font=("Segoe UI", 10)).pack(anchor=self.text_anchor, pady=(18, 8))
        presentation = tk.StringVar(value=self.values["presentation_filter"])
        for value, label in (("fsr1", "FSR 1 (spatial)"), ("linear", "Linear")):
            tk.Radiobutton(frame, text=self.tr(label), variable=presentation, value=value,
                           bg=BLACK, fg=PAPER, selectcolor="#26251f", activebackground=BLACK,
                           activeforeground=GOLD, font=("Segoe UI", 10)).pack(anchor=self.text_anchor, pady=2)
        tk.Label(frame, text=self.tr("Frame rate"), fg=PAPER, bg=BLACK,
                 font=("Segoe UI", 10)).pack(anchor=self.text_anchor, pady=(18, 8))
        frame_rate = tk.IntVar(value=self.values["frame_rate"])
        for value, label in ((30, "30 FPS (baseline)"), (60, "60 FPS (experimental)")):
            tk.Radiobutton(frame, text=self.tr(label), variable=frame_rate, value=value,
                           bg=BLACK, fg=PAPER, selectcolor="#26251f", activebackground=BLACK,
                           activeforeground=GOLD, font=("Segoe UI", 10)).pack(anchor=self.text_anchor, pady=2)
        import order1886
        tk.Label(frame, text=self.tr(order1886.timing.WARNING), justify=self.text_justify, wraplength=340,
                 fg=MUTED, bg=BLACK, font=("Segoe UI", 9)).pack(anchor=self.text_anchor, pady=(8, 4))
        vsync, fps = tk.BooleanVar(value=self.values["vsync"]), tk.BooleanVar(value=self.values["show_fps"])
        for label, variable in (("Vertical sync", vsync), ("Performance overlay (F9)", fps)):
            tk.Checkbutton(frame, text=self.tr(label), variable=variable, bg=BLACK, fg=PAPER,
                           selectcolor="#26251f", activebackground=BLACK, activeforeground=GOLD,
                           font=("Segoe UI", 10)).pack(anchor=self.text_anchor, pady=(10, 0))
        tk.Label(frame, text=self.tr("Leave runtime blank to use the packaged build.\nDisplay options apply on the next launch.\nPerformance depends on runtime compatibility."),
                 justify=self.text_justify, wraplength=340, fg=MUTED, bg=BLACK, font=("Segoe UI", 9)).pack(anchor=self.text_anchor, pady=22)
        row = tk.Frame(frame, bg=BLACK)
        row.pack(anchor=self.text_anchor)
        def save():
            values = dict(self.values, **{key: v.get().strip() for key, v in fields.items()})
            values.update(display_mode=display.get(), vsync=vsync.get(), show_fps=fps.get(),
                          presentation_filter=presentation.get(), frame_rate=frame_rate.get(),
                          aspect_ratio=aspect.get())
            try:
                save_settings(self.state / "settings.json", values)
            except (OSError, ValueError) as exc:
                messagebox.showerror(self.tr("Settings could not be saved"), self.tr(str(exc)), parent=self.root)
                return
            self.values = values
            self.sync_home()
            self.load_artwork()
            if not self.busy:
                self.refresh_status()
            self.back()
            self.draw()
        self.button(row, "Save settings", save).pack(side="left")
        self.button(row, "Back", self.back).pack(side="left", padx=12)

    def show_logs(self):
        tk = self.tk
        if self.log_window and self.log_window.winfo_exists():
            self.log_window.lift()
            return
        window = self.log_window = tk.Toplevel(self.root)
        window.title(self.tr("The Order: 1886 — Session log"))
        window.geometry("900x550")
        window.configure(bg=BLACK)
        window.transient(self.root)
        self.log_text = tk.Text(window, bg="#121310", fg=PAPER, font=("Consolas", 10),
                                wrap="word", relief="flat", padx=18, pady=18)
        self.log_text.pack(fill="both", expand=True)
        content = "".join(self.log_buffer)
        if not content:
            try:
                files = sorted((self.state / "logs").glob("*.log"), key=lambda p: p.stat().st_mtime)
                if files:
                    with files[-1].open("rb") as stream:
                        stream.seek(max(0, files[-1].stat().st_size - 256000))
                        content = stream.read().decode("utf-8", errors="replace")
            except OSError as exc:
                content = str(exc)
        self.log_text.insert("end", content or self.tr("No sessions recorded. Choose Verify files or Play to create a log.\n"))
        self.log_text.configure(state="disabled")
        row = tk.Frame(window, bg=BLACK, padx=12, pady=12)
        row.pack(fill="x")
        self.button(row, "Open log folder", self.open_log_folder).pack(side="left")
        self.button(row, "Stop session", self.stop).pack(side="left", padx=8)
        self.button(row, "Close", window.destroy).pack(side="right")

    def open_log_folder(self):
        directory = self.state / "logs"
        directory.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(directory))
        else:
            subprocess.Popen(["xdg-open", str(directory)])

    def run(self, mode):
        from tkinter import messagebox
        if self.busy:
            self.show_logs()
            return
        if not self.commit_home():
            return
        try:
            if mode == "play":
                validate_launch_game(Path(self.values["game_dir"]), dict(self.values, ui_language=self.language))
            save_settings(self.state / "settings.json", self.values)
            (self.state / "logs").mkdir(parents=True, exist_ok=True)
        except (OSError, ValueError) as exc:
            messagebox.showerror(self.tr("Cannot start session"), self.tr(str(exc)), parent=self.root)
            return
        self.busy = True
        self.session_cancel = threading.Event()
        self.stop_file = self.state / f"session-stop-{uuid.uuid4().hex}"
        self.session_started = time.time()
        self.session_mode = mode
        self.log_buffer = []
        if self.log_text and self.log_text.winfo_exists():
            self.log_text.configure(state="normal")
            self.log_text.delete("1.0", "end")
            self.log_text.configure(state="disabled")
        self.status = "Checking game files…" if mode == "verify" else "Starting experimental runtime…"
        self.detail = "Open View logs for progress."
        self.draw()
        if mode == "verify":
            self.show_logs()
        token = self.stop_file.stem.removeprefix("session-stop-")
        logfile = self.state / "logs" / f"launcher-{time.strftime('%Y%m%d-%H%M%S')}-{token[:8]}.log"
        command = backend_command(dict(self.values), mode, self.state, self.stop_file)
        self.session_thread = threading.Thread(target=session_worker,
            args=(command, logfile, self.events, self.session_cancel, self.stop_file, mode),
            daemon=True)
        self.session_thread.start()

    def poll(self):
        try:
            for _ in range(250):
                kind, value = self.events.get_nowait()
                if kind == "started":
                    self.process = value
                elif kind == "line":
                    self.log_buffer.append(value)
                    self.log_buffer = self.log_buffer[-2000:]
                    if value.startswith("Runtime started (PID") and not self.session_cancel.is_set():
                        self.status = "Auditing imports…" if self.session_mode == "verify" else "Runtime running"
                        self.detail = "Compatibility runtime is running. Gameplay remains unverified."
                        self.draw()
                    if self.log_text and self.log_text.winfo_exists():
                        self.log_text.configure(state="normal")
                        self.log_text.insert("end", value)
                        if int(self.log_text.index("end-1c").split(".")[0]) > 2500:
                            self.log_text.delete("1.0", "500.0")
                        self.log_text.see("end")
                        self.log_text.configure(state="disabled")
                else:
                    self.busy, self.process = False, None
                    if self.stop_file:
                        try:
                            self.stop_file.unlink(missing_ok=True)
                        except OSError:
                            pass
                    code, mode, stopped = value
                    self.status = ("Session stopped" if stopped else
                        ("File and import verification finished" if mode == "verify" else "Runtime session ended")
                        if code == 0 else self.tr("Session failed (exit {code})", code=code))
                    self.detail = "Review View logs. Gameplay and performance remain unverified."
                    report_path = self.state / "logs" / "last-run.json"
                    try:
                        if report_path.stat().st_mtime >= self.session_started:
                            report = read_settings(report_path)
                            reason = report.get("stop_reason") or report.get("error")
                            if reason:
                                self.detail = str(reason)[:240]
                            if report.get("missing_imports"):
                                self.status = "Import compatibility needs attention"
                                self.detail = self.tr("{count} imports are unresolved. See View logs.", count=report["missing_imports"])
                            if report.get("forced_stop"):
                                self.status = "Runtime timed out" if report.get("timed_out") else "Session stopped (forced shutdown)"
                                self.detail = "The runtime did not close in time. Review View logs before restarting."
                    except OSError:
                        pass
                    self.draw()
                    if self.closing:
                        self.root.destroy()
                        return
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def stop(self):
        if not self.busy:
            return
        self.session_cancel.set()
        try:
            if self.stop_file:
                self.stop_file.touch()
        except OSError as exc:
            self.events.put(("line", f"Could not request stop: {exc}\n"))
            return
        self.status = "Stopping session…"
        self.detail = "Waiting for the runtime to close. Keep the launcher open."
        self.draw()

    def close(self):
        from tkinter import messagebox
        if self.busy and not messagebox.askyesno(self.tr("Stop current session?"),
                self.tr("A session is running. Stop it and close the launcher?"), parent=self.root):
            return
        if self.busy:
            self.closing = True
            self.stop()
        else:
            self.root.destroy()


class DesktopLauncher(Launcher):
    """Reference launcher navigation, backed by the title-isolated Order runtime.

    Keep the classic cinematic home and its session worker. Settings on these
    pages use the same JSON and backend arguments; reference-specific INI keys,
    executable patches and update downloads do not belong to this runtime ABI.
    """

    def __init__(self, root, state: Path = STATE):
        super().__init__(root, state)
        root.geometry("1240x800")
        root.minsize(1120, 700)
        self.current_page = "home"
        self.page_controls = []
        self.mod_order = list(self.values["mod_order"]) if isinstance(self.values["mod_order"], list) else self.values["mod_order"]
        self.mods_source = self.values["mods_dir"]
        self.mod_config_invalid = not isinstance(self.values["mods_dir"], str) or type(self.values["mods_enabled"]) is not bool
        self.page_fields = {
            key: (self.tk.StringVar(value=value) if key == "mods_dir" else
                  self.tk.BooleanVar(value=value if type(value) is bool else False) if key == "mods_enabled" else
                  self.tk.BooleanVar(value=value) if isinstance(value, bool) else
                  self.tk.IntVar(value=value) if isinstance(value, int) else
                  self.tk.StringVar(value=value))
            for key, value in self.values.items() if key in SETTINGS_KEYS
        }
        self.page_host = self.tk.Frame(root, bg=BLACK)
        self.page_host.grid(row=0, column=1, sticky="nsew")
        self.pages, self.scrollers = {}, {}
        self.build_graphics()
        self.build_performance()
        self.build_game()
        self.build_advanced()
        self.show_page("home")
        root.bind("<MouseWheel>", self.page_wheel)
        root.bind("<FocusIn>", self.page_focus)

    def build_home(self):
        super().build_home()
        self.navigation.place_forget()
        # The launch bar remains accessible from every page, as in the reference.
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.canvas.grid_configure(column=1)
        self.console.grid_configure(column=1)
        side = self.tk.Frame(self.root, bg="#10110f", width=180)
        side.grid(row=0, column=0, rowspan=2, sticky="nsew")
        side.grid_propagate(False)
        side.columnconfigure(0, weight=1)
        side.rowconfigure(7, weight=1)
        self.sidebar_logo = None
        try:
            from PIL import ImageOps
            with self.Image.open(ASSETS / "logo-stacked.png") as logo:
                self.sidebar_logo = self.ImageTk.PhotoImage(ImageOps.contain(
                    logo.convert("RGBA"), (140, 100), self.Image.Resampling.LANCZOS))
        except OSError:
            pass
        self.tk.Label(side, image=self.sidebar_logo, text=self.tr("" if self.sidebar_logo else "The Order: 1886"),
                      bg="#10110f", fg=GOLD, font=("Georgia", 12), anchor="w").grid(
                          row=0, column=0, sticky="w", padx=20, pady=(24, 26))
        self.page_buttons = {}
        for index, name in enumerate(PAGES, 1):
            button = self.button(side, PAGE_TITLES[name], lambda n=name: self.show_page(n))
            button.configure(anchor=self.text_anchor, wraplength=140, bg="#10110f", highlightbackground="#10110f")
            button.grid(row=index, column=0, sticky="ew", padx=10, pady=3)
            self.page_buttons[name] = button
        self.tk.Label(side, text=self.tr("CUSA00076\nDevelopment preview"), bg="#10110f", fg=MUTED,
                      font=("Segoe UI", 9), justify=self.text_justify).grid(
                          row=8, column=0, sticky="sw", padx=22, pady=24)

    def scrolled_page(self, name, subtitle):
        tk = self.tk
        outer = tk.Frame(self.page_host, bg=BLACK)
        self.pages[name] = outer
        tk.Label(outer, text=self.tr(PAGE_TITLES[name]).upper(), bg=BLACK, fg=GOLD,
                 font=("Georgia", 23)).pack(anchor=self.text_anchor, padx=30, pady=(26, 8))
        tk.Label(outer, text=self.tr(subtitle), bg=BLACK, fg=MUTED, font=("Segoe UI", 10),
                 wraplength=660, justify=self.text_justify).pack(anchor=self.text_anchor, padx=30, pady=(0, 16))
        bar = tk.Scrollbar(outer, orient="vertical")
        bar.pack(side="right", fill="y")
        canvas = tk.Canvas(outer, bg=BLACK, highlightthickness=0, yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.configure(command=canvas.yview)
        body = tk.Frame(canvas, bg=BLACK, padx=30, pady=8)
        window = canvas.create_window(0, 0, anchor="nw", window=body)
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        self.scrollers[name] = (canvas, body)
        return body

    def section(self, frame, title, detail=""):
        self.tk.Label(frame, text=self.tr(title), bg=BLACK, fg=PAPER,
                      font=("Segoe UI", 12, "bold")).pack(anchor=self.text_anchor, pady=(16, 8))
        self.tk.Frame(frame, bg="#34352f", height=1).pack(fill="x", pady=(0, 8))
        if detail:
            self.note(frame, detail)

    def note(self, frame, text):
        self.tk.Label(frame, text=self.tr(text), bg=BLACK, fg=MUTED, wraplength=650,
                      justify=self.text_justify, font=("Segoe UI", 10)).pack(anchor=self.text_anchor, pady=(0, 10))

    def choices(self, frame, key, choices):
        for label, value in choices.items():
            button = self.tk.Radiobutton(frame, text=self.tr(label), value=value,
                variable=self.page_fields[key], bg=BLACK, fg=PAPER, selectcolor="#26251f",
                activebackground=BLACK, activeforeground=GOLD, font=("Segoe UI", 10))
            button.pack(anchor=self.text_anchor, pady=3)
            self.page_controls.append(button)

    def check(self, frame, key, label):
        button = self.tk.Checkbutton(frame, text=self.tr(label), variable=self.page_fields[key],
            bg=BLACK, fg=PAPER, selectcolor="#26251f", activebackground=BLACK,
            activeforeground=GOLD, font=("Segoe UI", 10))
        button.pack(anchor=self.text_anchor, pady=5)
        self.page_controls.append(button)
        return button

    def page_button(self, frame, label, command, changes=False):
        button = self.button(frame, label, command)
        button.pack(anchor=self.text_anchor, pady=6)
        if changes:
            self.page_controls.append(button)
        return button

    def save_button(self, frame):
        self.note(frame, "Changes apply to the next session.")
        self.page_button(frame, "Save settings", self.save_page_settings, changes=True)

    def build_graphics(self):
        frame = self.scrolled_page("graphics", "Display, aspect ratio and output scaling.")
        self.section(frame, "Display mode")
        self.choices(frame, "display_mode", DISPLAY)
        self.section(frame, "Aspect ratio", "Aspect changes require restarting the game.")
        self.choices(frame, "aspect_ratio", ASPECT_RATIO)
        self.section(frame, "Output scaling", "FSR 1 is spatial upscaling. Temporal FSR and DLSS are not available in this build.")
        self.choices(frame, "presentation_filter", UPSCALING)
        self.check(frame, "vsync", "Vertical sync")
        self.save_button(frame)

    def build_performance(self):
        import order1886
        frame = self.scrolled_page("performance", "Frame timing and the performance overlay.")
        self.section(frame, "Frame rate", order1886.timing.WARNING)
        self.choices(frame, "frame_rate", FRAME_RATE)
        self.section(frame, "Monitoring", "F9 toggles the overlay in the runtime. A selected limit is not a measured frame rate.")
        self.check(frame, "show_fps", "Performance overlay (F9)")
        self.section(frame, "Shader and GPU options",
            "Pipeline binaries, parallel warmup and background warmup stay disabled in the current "
            "compatibility profile. The reference port's GPU readback and memory switches require "
            "separate runtime validation. See the reuse assessment in the documentation.")
        self.save_button(frame)

    def path_field(self, frame, key, is_folder=True):
        from tkinter import filedialog
        row = self.tk.Frame(frame, bg=BLACK)
        row.pack(fill="x", pady=(0, 8))
        entry = self.tk.Entry(row, textvariable=self.page_fields[key], bg="#20201c", fg=PAPER,
            insertbackground=GOLD, relief="flat", font=("Segoe UI", 10), highlightthickness=1,
            highlightbackground="#514932", highlightcolor=GOLD)
        entry.pack(side="left", fill="x", expand=True, ipady=9)
        def browse():
            value = (filedialog.askdirectory(parent=self.root, title=self.tr("Choose mods folder" if key == "mods_dir" else "Choose extracted CUSA00076 folder"))
                     if is_folder else filedialog.askopenfilename(parent=self.root,
                         title=self.tr("Choose Order runtime"), filetypes=[(self.tr("Executable"), "*.exe")]))
            if value:
                self.page_fields[key].set(value)
                if key == "mods_dir":
                    self.mod_order = []  # A different source folder requires explicit selection.
                    self.refresh_mods()
        button = self.button(row, "Browse", browse)
        button.pack(side="right", padx=(8, 0))
        self.page_controls.extend((entry, button))

    def build_game(self):
        frame = self.scrolled_page("game", "Your game files, save backups and controls.")
        self.section(frame, "Game folder", "Use your own extracted CUSA00076 dump, including eboot.bin, sce_sys, sce_module, _data and archivemap.bin.")
        self.path_field(frame, "game_dir")
        self.save_button(frame)
        self.page_button(frame, "Verify files", lambda: self.run("verify"), changes=True)
        self.page_button(frame, "Create desktop shortcut", self.create_shortcut, changes=True)
        self.page_button(frame, "Add to Steam", self.add_steam, changes=True)
        self.section(frame, "Saves and data", self.tr("Data folder: {path}\nA backup is created before each game session. Restoring first backs up the current saves.", path=self.state))
        self.page_button(frame, "Open data folder", lambda: self.open_directory(self.state))
        self.backup_list = self.tk.Listbox(frame, height=4, bg="#20201c", fg=PAPER,
            selectbackground=GOLD, selectforeground=BLACK, exportselection=False,
            font=("Consolas", 10), highlightcolor=GOLD)
        self.backup_list.pack(fill="x", pady=8)
        self.note(frame, "Select a backup, then Restore or Play. Restoration asks for confirmation and backs up the current saves. Choose Continue or Load after the game starts.")
        self.page_button(frame, "Back up saves now", self.backup_saves, changes=True)
        self.page_button(frame, "Restore selected backup", self.restore_saves, changes=True)
        self.section(frame, "Game patches and mods",
            "The 60 FPS and aspect-ratio recipes use hash-checked prepared copies; original game files "
            "stay unchanged. Configure them in Performance and Graphics. Asset mods are selected below; external executable patches and updates are unsupported.")
        self.section(frame, "Asset mods", "Each mod is a folder containing _data assets and optionally archivemap.bin. New folders stay disabled. Later enabled mods win conflicts. Original files remain unchanged.")
        self.path_field(frame, "mods_dir")
        self.check(frame, "mods_enabled", "Enable asset mods").configure(command=self.refresh_mods)
        self.mod_list = self.tk.Listbox(frame, height=5, exportselection=False, bg="#20201c", fg=PAPER,
            selectbackground=GOLD, selectforeground=BLACK, font=("Segoe UI", 10), highlightcolor=GOLD)
        self.mod_list.pack(fill="x", pady=8)
        self.page_controls.append(self.mod_list)
        self.page_button(frame, "Refresh mods and conflicts", self.refresh_mods, changes=True)
        self.page_button(frame, "Enable / disable selected mod", self.toggle_mod, changes=True)
        self.page_button(frame, "Move selected mod earlier", lambda: self.move_mod(-1), changes=True)
        self.page_button(frame, "Move selected mod later", lambda: self.move_mod(1), changes=True)
        self.mod_notice = self.tk.Label(frame, bg=BLACK, fg=MUTED, wraplength=650,
            justify=self.text_justify, font=("Segoe UI", 10))
        self.mod_notice.pack(anchor=self.text_anchor, pady=(0, 10))
        self.refresh_mods()
        self.save_button(frame)
        self.section(frame, "Controls", "Mouse movement controls the right stick. Left mouse fires (R2); right mouse aims (L2). "
                     "Press Esc to release the cursor and F6 to capture or release it. Alt-Tab and text entry release capture. "
                     "WASD moves, arrow keys control the camera, I/J/K/L are the d-pad, Enter opens Options. "
                     "Controllers remain available. Direct 1:1 camera hooks are not implemented.")
        self.check(frame, "mouse_look", "Enable mouse look")
        self.check(frame, "mouse_invert_y", "Invert mouse Y")
        sensitivity = self.tk.Scale(frame, from_=10, to=500, orient="horizontal", resolution=1,
                      variable=self.page_fields["mouse_sensitivity"], label=self.tr("Mouse sensitivity (%)"),
                      bg=BLACK, fg=PAPER, highlightthickness=0)
        sensitivity.pack(fill="x", pady=6)
        self.page_controls.append(sensitivity)
        self.note(frame, "Save controls before starting the game.")
        self.save_button(frame)

    def refresh_mods(self):
        import order1886_mods as mods
        self.mod_names = []
        self.mod_list.delete(0, "end")
        try:
            root = self.page_fields["mods_dir"].get().strip()
            if root != self.mods_source:
                self.mod_order = []
                self.mods_source = root
            enabled = self.page_fields["mods_enabled"].get()
            mod_root = mods.resolve_root(root, ROOT)
            mods.validate_config(mod_root, enabled, self.mod_order)
            available = mods.discover(mod_root) if mod_root else []
            self.mod_names = [name for name in self.mod_order if name in available] + [name for name in available if name not in self.mod_order]
            for name in self.mod_names:
                self.mod_list.insert("end", self.tr("{state}: {name}", state=self.tr("Enabled" if name in self.mod_order else "Disabled"), name=name))
            game = Path(self.page_fields["game_dir"].get())
            game = game if game.is_absolute() else ROOT / game
            _, conflicts = mods.plan(game, mod_root, enabled, self.mod_order)
            message = self.tr("{count} selected mods; {conflicts} file overrides. Later mods win.", count=len(self.mod_order), conflicts=len(conflicts))
            if not enabled:
                message = self.tr("Mods are off. The original game folder will be mounted.") + "\n" + message
            if conflicts:
                message += "\n" + "\n".join(f"{path}: {previous} → {winner}" for path, previous, winner in conflicts[:10])
        except (OSError, ValueError) as error:
            message = self.tr("Mods need attention: {error}", error=error)
        if self.mod_config_invalid:
            message = self.tr("Saved mod settings are invalid. Review the folder and enabled state, then save settings.") + "\n" + message
        self.mod_notice.configure(text=message)

    def toggle_mod(self):
        if self.busy or not self.mod_list.curselection() or not isinstance(self.mod_order, list):
            return
        name = self.mod_names[self.mod_list.curselection()[0]]
        if name in self.mod_order:
            self.mod_order.remove(name)
        else:
            self.mod_order.append(name)
        self.refresh_mods()
        self.mod_list.selection_set(self.mod_names.index(name))

    def move_mod(self, direction):
        if self.busy or not self.mod_list.curselection() or not isinstance(self.mod_order, list):
            return
        name = self.mod_names[self.mod_list.curselection()[0]]
        if name not in self.mod_order:
            return
        index = self.mod_order.index(name)
        target = index + direction
        if 0 <= target < len(self.mod_order):
            self.mod_order[index], self.mod_order[target] = self.mod_order[target], self.mod_order[index]
            self.refresh_mods()
            self.mod_list.selection_set(self.mod_names.index(name))

    def create_shortcut(self):
        from tkinter import messagebox
        try:
            shortcut = create_desktop_shortcut()
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            messagebox.showerror(self.tr("Shortcut could not be created"), self.tr(str(error)), parent=self.root)
            return
        messagebox.showinfo(self.tr("Desktop shortcut created"), self.tr(str(shortcut)), parent=self.root)

    def add_steam(self):
        from tkinter import messagebox
        from order1886_steam import add_to_steam, SteamIntegrationError
        if self.busy:
            messagebox.showerror(self.tr("Steam shortcut unavailable"), self.tr("Stop the game before changing shortcuts."), parent=self.root)
            return
        try:
            add_to_steam(ROOT, state=self.state)
        except (OSError, SteamIntegrationError) as error:
            messagebox.showerror(self.tr("Could not add to Steam"), self.tr(str(error)), parent=self.root)
            return
        messagebox.showinfo(self.tr("Added to Steam"), self.tr("Open Steam to find The Order: 1886 in your library. "
                            "It uses your saved launcher settings."), parent=self.root)

    def clear_cache(self):
        from tkinter import messagebox
        from order1886_cache import clear_shader_cache
        if self.busy:
            messagebox.showerror(self.tr("Shader cache is in use"), self.tr("Stop the game before clearing its shader cache."), parent=self.root)
            return
        if not messagebox.askyesno(self.tr("Clear shader cache?"), self.tr("Remove this installation's compiled shaders? "
                                  "The next launch will rebuild them and may stutter. Saves, settings and game files are preserved."),
                                  parent=self.root):
            return
        try:
            removed = clear_shader_cache(self.state)
        except (OSError, ValueError, RuntimeError) as error:
            messagebox.showerror(self.tr("Shader cache could not be cleared"), self.tr(str(error)), parent=self.root)
            return
        messagebox.showinfo(self.tr("Shader cache"), self.tr("Shader cache cleared. The next launch will rebuild it."
                            if removed else "The shader cache is already empty."), parent=self.root)

    def build_advanced(self):
        frame = self.scrolled_page("advanced", "Runtime selection, files, logs and support.")
        self.section(frame, "Launcher language", "Save the language, then restart the launcher and game to apply it. The game needs matching installed language assets.")
        from tkinter import ttk
        self.language_choice = self.tk.StringVar(value=LANGUAGES[self.language])
        self.language_combo = ttk.Combobox(frame, textvariable=self.language_choice,
            values=list(LANGUAGES.values()), state="readonly", style="Order.TCombobox",
            font=("Segoe UI", 11), justify=self.text_justify)
        self.language_combo.pack(fill="x", pady=(0, 8))
        self.page_controls.append(self.language_combo)
        self.page_button(frame, "Save language", self.save_language, changes=True)
        self.section(frame, "Runtime executable (optional)", "Leave blank to use this installation's runtime. Build identity is checked before launch.")
        self.path_field(frame, "runtime", is_folder=False)
        self.save_button(frame)
        self.section(frame, "Files and diagnostics")
        self.page_button(frame, "Open installation folder", lambda: self.open_directory(ROOT))
        self.page_button(frame, "View session log", self.show_logs)
        self.page_button(frame, "Open log folder", self.open_log_folder)
        self.page_button(frame, "Clear shader cache", self.clear_cache, changes=True)
        self.note(frame, "Include last-run.json, the matching boot log, runtime SHA256 and reproduction steps in a report. Review logs for personal paths before sharing.")
        self.section(frame, "Updates and support", "Release availability is shown on GitHub. Downloads are installed manually; your saves and settings remain in the data folder.")
        import webbrowser
        self.page_button(frame, "Releases", lambda: webbrowser.open("https://github.com/JulioCacko/The-Order-1886_pc/releases"))
        self.page_button(frame, "Report a problem", lambda: webbrowser.open("https://github.com/JulioCacko/The-Order-1886_pc/issues"))

    def save_language(self):
        from tkinter import messagebox
        if self.busy:
            return
        language = next(code for code, label in LANGUAGES.items() if label == self.language_choice.get())
        values = dict(read_settings(self.state / "settings.json"), ui_language=language)
        try:
            save_settings(self.state / "settings.json", values)
        except (OSError, ValueError) as exc:
            messagebox.showerror(self.tr("Settings could not be saved"), self.tr(str(exc)), parent=self.root)
            return
        self.values["ui_language"] = language
        self.page_fields["ui_language"].set(language)
        messagebox.showinfo(self.tr("Language saved"), self.tr("Restart the launcher to apply its language. The next game launch requests the same language; missing game assets may fall back."), parent=self.root)

    def sync_page_fields(self):
        for key, variable in self.page_fields.items():
            variable.set(self.values[key])
        self.mod_order = list(self.values["mod_order"]) if isinstance(self.values["mod_order"], list) else self.values["mod_order"]
        self.mods_source = self.values["mods_dir"]
        if hasattr(self, "mod_list"):
            self.refresh_mods()

    def save_page_settings(self):
        from tkinter import messagebox
        if self.busy:
            return False
        if self.page_fields["mods_dir"].get().strip() != self.mods_source:
            self.refresh_mods()
        values = dict(self.values, **{key: variable.get() for key, variable in self.page_fields.items()})
        values["mod_order"] = self.mod_order
        values["game_dir"], values["runtime"] = values["game_dir"].strip(), values["runtime"].strip()
        if not values["game_dir"]:
            messagebox.showerror(self.tr("Choose a game folder"), self.tr("Select an extracted CUSA00076 folder."), parent=self.root)
            return False
        try:
            import order1886_mods as mods
            mods.plan(Path(values["game_dir"]), values["mods_dir"], values["mods_enabled"], values["mod_order"])
            save_settings(self.state / "settings.json", values)
        except (OSError, ValueError) as exc:
            messagebox.showerror(self.tr("Settings could not be saved"), self.tr(str(exc)), parent=self.root)
            return False
        self.values = values
        self.sync_home()
        self.load_artwork()
        self.refresh_status()
        self.draw()
        self.mod_config_invalid = False
        return True

    def show_page(self, name):
        if name not in PAGES:
            raise ValueError(f"Unknown launcher page: {name}")
        if not hasattr(self, "pages"):
            return
        # Navigation never writes settings. Unsaved edits stay until Save or a launch-bar change.
        for page in self.pages.values():
            page.pack_forget()
        self.current_page = name
        if name == "home":
            self.page_host.grid_remove()
        else:
            self.page_host.grid()
            self.page_host.tkraise()
            self.pages[name].pack(fill="both", expand=True)
        for key, button in self.page_buttons.items():
            button.configure(bg="#29271e" if key == name else "#10110f",
                             fg=GOLD if key == name else PAPER)
        if name == "game":
            self.refresh_backups()
        self.draw()

    def commit_home(self):
        result = super().commit_home()
        if result and hasattr(self, "page_fields"):
            self.sync_page_fields()
        return result

    def settings(self):
        self.show_page("graphics")

    def run(self, mode="play"):
        if not self.busy and self.current_page != "home" and not self.save_page_settings():
            return
        if not self.busy and self.current_page == "game" and mode == "play" and self.backup_list.curselection():
            if not self.save_action(restore=True):
                return
        super().run(mode)

    def back(self, event=None):
        self.show_page("home")
        self.page_buttons["home"].focus_set()

    def activate(self, event=None):
        if event and event.widget.winfo_class() in ("Button", "TButton"):
            event.widget.invoke()
            return "break"
        if getattr(self, "current_page", "home") == "home":
            return super().activate(event)

    def draw(self):
        super().draw()
        for widget in getattr(self, "page_controls", ()):
            widget.configure(state="disabled" if self.busy else
                             "readonly" if widget.winfo_class() == "TCombobox" else "normal")

    def page_wheel(self, event):
        if self.current_page in self.scrollers and event.widget.winfo_toplevel() == self.root:
            canvas, _ = self.scrollers[self.current_page]
            canvas.yview_scroll(-int(event.delta / 120), "units")

    def page_focus(self, event):
        if self.current_page not in self.scrollers:
            return
        canvas, body = self.scrollers[self.current_page]
        if str(event.widget).startswith(str(body) + "."):
            top = event.widget.winfo_rooty() - body.winfo_rooty()
            visible = canvas.canvasy(0)
            if top < visible or top + event.widget.winfo_height() > visible + canvas.winfo_height():
                canvas.yview_moveto(max(0, top - 20) / max(1, body.winfo_height()))

    def open_directory(self, directory):
        from tkinter import messagebox
        try:
            directory.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(directory))
            else:
                subprocess.Popen(["xdg-open", str(directory)])
        except OSError as exc:
            messagebox.showerror(self.tr("Could not open folder"), self.tr(str(exc)), parent=self.root)

    def refresh_backups(self):
        import order1886
        self.backup_list.delete(0, "end")
        for name in order1886.save_backup.list_backups(self.state):
            self.backup_list.insert("end", name)

    def save_action(self, restore=False):
        from tkinter import messagebox
        import order1886
        if self.busy:
            return False
        try:
            # Apply the same original-file boundary as a normal launcher settings write.
            game = Path(self.values["game_dir"])
            game = (game if game.is_absolute() else ROOT / game).resolve()
            state = self.state.resolve()
            if state == game or game in state.parents:
                raise ValueError("Launcher state must be outside the selected game folder.")
            if restore:
                selected = self.backup_list.curselection()
                if not selected:
                    messagebox.showinfo(self.tr("Choose a save backup"),
                        self.tr("Select a backup in the list before restoring."), parent=self.root)
                    return False
                name = self.backup_list.get(selected[0])
                if not messagebox.askyesno(self.tr("Restore save backup?"),
                        self.tr("Restore {name}? Current saves will be backed up first.", name=name), parent=self.root):
                    return False
            state.mkdir(parents=True, exist_ok=True)
            with order1886.session_lock(state):
                if restore:
                    order1886.save_backup.restore(state, name)
                elif order1886.save_backup.backup(state) is None:
                    messagebox.showinfo(self.tr("No saves yet"), self.tr("There are no saves to back up."), parent=self.root)
                    return False
            self.refresh_backups()
            return True
        except (OSError, ValueError, RuntimeError) as exc:
            messagebox.showerror(self.tr("Save operation failed"), self.tr(str(exc)), parent=self.root)
            return False

    def backup_saves(self):
        self.save_action()

    def restore_saves(self):
        from tkinter import messagebox
        if self.save_action(restore=True):
            messagebox.showinfo(self.tr("Save restored"),
                self.tr("The selected backup is restored. Start the game and choose Continue or Load; this does not load a running game."), parent=self.root)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--run-backend":
        attach_stdio()
        import order1886
        return order1886.main(argv[1:])
    parser = argparse.ArgumentParser(description="The Order: 1886 launcher")
    parser.add_argument("--state-dir", type=Path, default=STATE)
    parser.add_argument("--smoke-test", action="store_true", help="Open, render, check settings and close")
    parser.add_argument("--play", action="store_true",
                        default=FROZEN and Path(sys.executable).name.casefold() == "play the order 1886.exe",
                        help="Start with saved settings; open setup if configuration is missing")
    parser.add_argument("--classic", action="store_true", help="Open the original cinematic launcher")
    args = parser.parse_args(argv)
    if args.smoke_test:
        attach_stdio()
    if os.name == "nt":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TheOrder1886.Launcher")
        except (AttributeError, OSError):
            pass
    if args.play and not args.smoke_test:
        def show_play_error(message):
            from tkinter import messagebox
            language = read_settings(args.state_dir / "settings.json").get("ui_language", "en")
            messagebox.showerror(translate("Cannot launch The Order: 1886", language), message)
        code = run_saved_game(args.state_dir.resolve(), on_error=show_play_error)
        if code is not None:
            return code
    import tkinter as tk
    root = tk.Tk()
    smoke_state = tempfile.TemporaryDirectory(prefix="order1886-launcher-smoke-") if args.smoke_test else None
    launcher_type = Launcher if args.classic else DesktopLauncher
    app = launcher_type(root, Path(smoke_state.name) if smoke_state else args.state_dir.resolve())
    smoke_errors = []
    if args.smoke_test:
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        def smoke():
            try:
                import order1886_cache
                import order1886_mods
                import order1886_steam
                if isinstance(app, DesktopLauncher):
                    for page in PAGES:
                        app.show_page(page)
                        root.update()
                        if app.current_page != page:
                            raise RuntimeError(f"Navigation failed for {page}")
                    app.page_fields["display_mode"].set("windowed")
                    app.page_fields["presentation_filter"].set("linear")
                    app.page_fields["frame_rate"].set(60)
                    app.page_fields["show_fps"].set(False)
                    if not app.save_page_settings():
                        raise RuntimeError("Page settings did not save")
                    saved = read_settings(app.state / "settings.json")
                    command = backend_command(saved, state=app.state)
                    for key, expected in (("--display-mode", "windowed"),
                            ("--presentation-filter", "linear"), ("--frame-rate", "60"), ("--show-fps", "0")):
                        if command[command.index(key) + 1] != expected:
                            raise RuntimeError(f"Page setting did not affect {key}")
                    app.back()
                    root.update()
                    if app.page_host.winfo_ismapped():
                        raise RuntimeError("Home did not hide the settings pages")
                    root.destroy()
                    return
                if app.values["show_fps"] is not True:
                    raise RuntimeError("A fresh launcher must enable the performance overlay")
                if app.values["presentation_filter"] != "fsr1":
                    raise RuntimeError("A fresh launcher must select FSR 1 output scaling")
                if app.values["frame_rate"] != 30:
                    raise RuntimeError("A fresh launcher must retain the 30 FPS baseline")
                root.geometry("940x620")
                app.settings()
                root.update()
                widgets = list(descendants(app.settings_frame))
                next(w for w in widgets if w.winfo_class() == "Radiobutton" and w.cget("text") == "Windowed").invoke()
                next(w for w in widgets if w.winfo_class() == "Radiobutton" and w.cget("text") == "Linear").invoke()
                next(w for w in widgets if w.winfo_class() == "Radiobutton" and
                     w.cget("text") == "60 FPS (experimental)").invoke()
                if not any(w.winfo_class() == "Label" and "Chapters 6 and 9" in w.cget("text")
                           for w in widgets):
                    raise RuntimeError("Experimental timing warning is missing")
                for label in ("Vertical sync", "Performance overlay (F9)"):
                    next(w for w in widgets if w.winfo_class() == "Checkbutton" and w.cget("text") == label).invoke()
                save = next(w for w in widgets if w.winfo_class() == "Button" and w.cget("text") == "Save settings")
                root.focus_force()
                save.focus_set()
                root.update()
                if not root.winfo_rooty() <= save.winfo_rooty() < root.winfo_rooty() + root.winfo_height() - save.winfo_height():
                    raise RuntimeError("Settings focus did not scroll Save into view")
                save.invoke()
                saved = read_settings(app.state / "settings.json")
                if saved.get("display_mode") != "windowed" or saved.get("vsync") is not False or \
                        saved.get("show_fps") is not False or saved.get("presentation_filter") != "linear":
                    raise RuntimeError("Settings controls did not persist their values")
                if saved.get("frame_rate") != 60:
                    raise RuntimeError("Experimental frame-rate selection did not persist")
                command = backend_command(saved, "play", app.state)
                for key, expected in (("--display-mode", "windowed"), ("--vsync", "0"), ("--show-fps", "0"),
                                      ("--presentation-filter", "linear")):
                    if command[command.index(key) + 1] != expected:
                        raise RuntimeError(f"Settings did not affect {key}")
                if command[command.index("--frame-rate") + 1] != "60":
                    raise RuntimeError("Frame-rate selection did not affect the backend command")
                if FROZEN:
                    desktop = Path(smoke_state.name) / "Shortcut Desktop ç"
                    first = create_desktop_shortcut(ROOT, desktop)
                    second = create_desktop_shortcut(ROOT, desktop)
                    if first != second or not first.is_file() or len(list(desktop.glob("*.lnk"))) != 1:
                        raise RuntimeError("Desktop shortcut must be repeatable and installation-local")
                app.play_button.focus_set()
                if root.focus_get() != app.play_button:
                    raise RuntimeError("Play must be keyboard focusable")
            except Exception as exc:
                smoke_errors.append(str(exc))
                print(f"Launcher smoke failed: {exc}", file=sys.stderr, flush=True)
            root.destroy()
        root.after(800, smoke)
    try:
        root.mainloop()
    finally:
        if smoke_state:
            smoke_state.cleanup()
    if smoke_errors:
        return 1
    if args.smoke_test:
        print("Launcher smoke passed: settings, command values, focus scrolling and navigation.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
