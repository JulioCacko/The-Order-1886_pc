#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""The Order: 1886 desktop launcher. Its settings and logs are title-isolated."""
from __future__ import annotations

import argparse
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

FROZEN = getattr(sys, "frozen", False)
ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
BUNDLE = Path(getattr(sys, "_MEIPASS", ROOT))
ASSETS = BUNDLE / "launcher" / "order1886"
sys.path.insert(0, str(BUNDLE))
STATE = ROOT / "user" / "order1886"
GOLD, PAPER, MUTED, BLACK = "#d4bd75", "#e9e5d8", "#a8a497", "#0b0b0a"
DISPLAY = {"Windowed": "windowed", "Borderless": "borderless", "Fullscreen": "fullscreen"}
UPSCALING = {"FSR 1": "fsr1", "Linear": "linear"}
FRAME_RATE = {"30 FPS": 30, "60 FPS (experimental)": 60}
ASPECT_RATIO = {"Full screen 16:9 (experimental)": "16:9", "Original cinematic aspect": "original"}


def read_settings(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(path: Path, values: dict) -> None:
    if values.get("game_dir"):
        game, state = Path(values["game_dir"]).resolve(), path.parent.resolve()
        if state == game or game in state.parents:
            raise ValueError("Launcher state must be outside the selected game folder.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def backend_command(values: dict, mode: str = "play", state: Path = STATE,
                    stop_file: Path | None = None) -> list[str]:
    command = ([sys.executable, "--run-backend"] if FROZEN else
               [sys.executable, str(ROOT / "order1886.py")])
    command += ["--game-dir", values["game_dir"], "--state-dir", str(state),
                "--display-mode", values["display_mode"],
                "--vsync", str(int(values["vsync"])),
                 "--show-fps", str(int(values["show_fps"])),
                 "--presentation-filter", values.get("presentation_filter", "fsr1"),
                 "--frame-rate", str(values.get("frame_rate", 30)),
                 "--aspect-ratio", values.get("aspect_ratio", "16:9")]
    if values.get("runtime"):
        command += ["--runtime", values["runtime"]]
    if mode == "verify":
        command += ["--check-imports"]
    if stop_file is not None:
        command += ["--stop-file", str(stop_file)]
    return command


def session_worker(command: list[str], logfile: Path, events: queue.Queue,
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
        saved = read_settings(state / "settings.json")
        self.values = {
            "game_dir": str(saved.get("game_dir", order1886.default_game_dir())),
            "runtime": str(saved.get("runtime", "")),
            "display_mode": saved.get("display_mode", "borderless"),
            "vsync": bool(saved.get("vsync", True)),
            "show_fps": bool(saved.get("show_fps", True)),
            "presentation_filter": saved.get("presentation_filter", "fsr1"),
            "frame_rate": saved.get("frame_rate", 30),
            "aspect_ratio": saved.get("aspect_ratio", "16:9"),
        }
        if self.values["display_mode"] not in ("windowed", "borderless", "fullscreen"):
            self.values["display_mode"] = "borderless"
        if self.values["presentation_filter"] not in ("linear", "fsr1"):
            self.values["presentation_filter"] = "fsr1"
        if type(self.values["frame_rate"]) is not int or self.values["frame_rate"] not in (30, 60):
            self.values["frame_rate"] = 30
        if self.values["aspect_ratio"] not in ("original", "16:9"):
            self.values["aspect_ratio"] = "16:9"
        root.title("The Order: 1886")
        root.configure(bg=BLACK)
        root.geometry("1160x760")
        root.minsize(940, 620)
        try:
            root.iconbitmap(str(ASSETS / "order1886.ico"))
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
        tk.Label(folder, text="Game folder", bg="#141513", fg=PAPER,
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
            tk.Label(group, text=label, fg=PAPER, bg="#141513",
                     font=("Segoe UI", 10), anchor="w").pack(fill="x", pady=(0, 6))
            variable = self.home_fields[key] = tk.StringVar()
            combo = ttk.Combobox(group, textvariable=variable, values=list(choices),
                                 state="readonly", style="Order.TCombobox", width=1,
                                 font=("Segoe UI", 11))
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
        self.warning = tk.Label(notice, text="Experimental runtime. Gameplay is not yet verified.",
            fg=GOLD, bg="#141513", font=("Segoe UI", 10), anchor="w", justify="left")
        self.warning.pack(side="left", fill="x", expand=True)
        self.play_hint = tk.Label(controls, text="Enter to play", fg=MUTED, bg="#141513",
                                 font=("Segoe UI", 9))
        self.play_hint.grid(row=1, column=3, pady=(10, 0))
        self.sync_home()

    def sync_home(self):
        self.home_fields["game_dir"].set(self.values["game_dir"])
        for key, choices in (("display_mode", DISPLAY), ("presentation_filter", UPSCALING),
                             ("frame_rate", FRAME_RATE)):
            self.home_fields[key].set(next(label for label, value in choices.items()
                                          if value == self.values[key]))

    def commit_home(self):
        from tkinter import messagebox
        values = dict(self.values, game_dir=self.home_fields["game_dir"].get().strip())
        if not values["game_dir"]:
            messagebox.showerror("Choose a game folder", "Select the extracted CUSA00076 folder before continuing.", parent=self.root)
            return False
        for key, choices in (("display_mode", DISPLAY), ("presentation_filter", UPSCALING),
                             ("frame_rate", FRAME_RATE)):
            values[key] = choices[self.home_fields[key].get()]
        try:
            save_settings(self.state / "settings.json", values)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Settings could not be saved", str(exc), parent=self.root)
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
        value = filedialog.askdirectory(parent=self.root, title="Choose extracted CUSA00076 folder",
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
        """Use the generated launcher plate; original game files remain read-only."""
        artwork = Path(self.values["game_dir"]) / "sce_sys"
        self.backdrop = None
        self.artwork_size = None
        for path in (ASSETS / "launcher-art.png", artwork / "pic0.png", ASSETS / "background.png"):
            try:
                with self.Image.open(path) as image:
                    self.backdrop = image.convert("RGB")
                break
            except OSError:
                continue
        try:
            with self.Image.open(artwork / "icon0.png") as icon:
                self.icon_photo = self.ImageTk.PhotoImage(icon.copy())
            self.root.iconphoto(True, self.icon_photo)
        except (OSError, self.tk.TclError):
            pass

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
        size = min(67, max(36, int(w * .0436)))
        for text, y, pixels, width in (("THEORDER", h * .09, size, w * .38),
                ("1886", h * .09 + size * 1.04, int(size * .78), w * .13)):
            face = tkfont.Font(family="Georgia", size=-pixels)
            gap = (width - sum(face.measure(letter) for letter in text)) / (len(text) - 1)
            x = w * .037
            for letter in text:
                c.create_text(x, y, text=letter, font=("Georgia", -pixels), fill=GOLD, anchor="nw")
                x += face.measure(letter) + gap
        c.create_line(w * .038, h * .09 + size * 2.05,
                      w * .245, h * .09 + size * 2.05, fill=GOLD)
        self.readiness.configure(text=self.status.replace("CUSA00076  /  ", ""),
                                 fg="#aec58f" if "Game files found" in self.status else MUTED,
                                 wraplength=210, justify="left")
        self.readiness_icon.delete("all")
        if "Game files found" in self.status:
            self.readiness_icon.create_oval(1, 1, 21, 21, fill="#aec58f", outline="")
            self.readiness_icon.create_line(6, 11, 10, 15, 16, 7, fill=BLACK, width=2)
        self.play_button.configure(text="Stopping…" if self.busy and self.session_cancel.is_set()
                                   else "Stop session" if self.busy else "Play",
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
                label_width = tkfont.Font(font=self.play_button.cget("font")).measure("Play")
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
        warning = "Experimental runtime. Gameplay is not yet verified."
        if self.values["frame_rate"] == 60:
            import order1886
            warning += "\n" + order1886.timing.WARNING
        if self.detail != "Experimental runtime. Gameplay is not yet verified.":
            warning += "\n" + self.detail
        self.warning.configure(text=warning, wraplength=max(480, int((w - 84) * .73) - 36))
        self.play_hint.configure(text="View logs for progress" if self.busy else "Enter to play")

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
        return self.tk.Button(parent, text=text, command=command, bg="#25241f", fg=PAPER,
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
        tk.Label(frame, text="SETTINGS", fg=GOLD, bg=BLACK, font=("Georgia", 21)).pack(anchor="w", pady=(15, 25))
        fields = {}
        for key, label, is_folder in (("game_dir", "Game folder", True),
                            ("runtime", "Runtime executable (optional)", False)):
            tk.Label(frame, text=label, fg=PAPER, bg=BLACK, font=("Segoe UI", 10)).pack(anchor="w", pady=(8, 7))
            row = tk.Frame(frame, bg=BLACK)
            row.pack(fill="x")
            variable = fields[key] = tk.StringVar(value=self.values[key])
            entry = tk.Entry(row, textvariable=variable, bg="#20201c", fg=PAPER, insertbackground=GOLD,
                             relief="flat", font=("Segoe UI", 10), highlightthickness=1,
                             highlightbackground="#514932", highlightcolor=GOLD)
            entry.pack(side="left", fill="x", expand=True, ipady=10)
            def browse(v=variable, folder=is_folder):
                value = (filedialog.askdirectory(parent=self.root, title="Choose extracted CUSA00076 folder") if folder else
                         filedialog.askopenfilename(parent=self.root, title="Choose The Order: 1886 runtime", filetypes=[("Order runtime", "order1886-runtime.exe"), ("Executables", "*.exe")]))
                if value:
                    v.set(value)
            self.button(row, "Browse", browse).pack(side="right", padx=(8, 0))
        tk.Label(frame, text="Display mode", fg=PAPER, bg=BLACK, font=("Segoe UI", 10)).pack(anchor="w", pady=(23, 8))
        display = tk.StringVar(value=self.values["display_mode"])
        for mode in ("windowed", "borderless", "fullscreen"):
            tk.Radiobutton(frame, text=mode.capitalize(), variable=display, value=mode,
                           bg=BLACK, fg=PAPER, selectcolor="#26251f", activebackground=BLACK,
                           activeforeground=GOLD, font=("Segoe UI", 10)).pack(anchor="w", pady=2)
        tk.Label(frame, text="Aspect ratio", fg=PAPER, bg=BLACK,
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(18, 8))
        aspect = tk.StringVar(value=self.values["aspect_ratio"])
        for label, value in ASPECT_RATIO.items():
            tk.Radiobutton(frame, text=label, variable=aspect, value=value,
                           bg=BLACK, fg=PAPER, selectcolor="#26251f", activebackground=BLACK,
                           activeforeground=GOLD, font=("Segoe UI", 10)).pack(anchor="w", pady=2)
        tk.Label(frame, text="Aspect changes apply after restarting the game.", fg=MUTED, bg=BLACK,
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(5, 0))
        tk.Label(frame, text="Output scaling", fg=PAPER, bg=BLACK,
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(18, 8))
        presentation = tk.StringVar(value=self.values["presentation_filter"])
        for value, label in (("fsr1", "FSR 1 (spatial)"), ("linear", "Linear")):
            tk.Radiobutton(frame, text=label, variable=presentation, value=value,
                           bg=BLACK, fg=PAPER, selectcolor="#26251f", activebackground=BLACK,
                           activeforeground=GOLD, font=("Segoe UI", 10)).pack(anchor="w", pady=2)
        tk.Label(frame, text="Frame rate", fg=PAPER, bg=BLACK,
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(18, 8))
        frame_rate = tk.IntVar(value=self.values["frame_rate"])
        for value, label in ((30, "30 FPS (baseline)"), (60, "60 FPS (experimental)")):
            tk.Radiobutton(frame, text=label, variable=frame_rate, value=value,
                           bg=BLACK, fg=PAPER, selectcolor="#26251f", activebackground=BLACK,
                           activeforeground=GOLD, font=("Segoe UI", 10)).pack(anchor="w", pady=2)
        import order1886
        tk.Label(frame, text=order1886.timing.WARNING, justify="left", wraplength=340,
                 fg=MUTED, bg=BLACK, font=("Segoe UI", 9)).pack(anchor="w", pady=(8, 4))
        vsync, fps = tk.BooleanVar(value=self.values["vsync"]), tk.BooleanVar(value=self.values["show_fps"])
        for label, variable in (("Vertical sync", vsync), ("Performance overlay (F9)", fps)):
            tk.Checkbutton(frame, text=label, variable=variable, bg=BLACK, fg=PAPER,
                           selectcolor="#26251f", activebackground=BLACK, activeforeground=GOLD,
                           font=("Segoe UI", 10)).pack(anchor="w", pady=(10, 0))
        tk.Label(frame, text="Leave runtime blank to use the packaged build.\nDisplay options apply on the next launch.\nPerformance depends on runtime compatibility.",
                 justify="left", wraplength=340, fg=MUTED, bg=BLACK, font=("Segoe UI", 9)).pack(anchor="w", pady=22)
        row = tk.Frame(frame, bg=BLACK)
        row.pack(anchor="w")
        def save():
            values = {key: v.get().strip() for key, v in fields.items()}
            values.update(display_mode=display.get(), vsync=vsync.get(), show_fps=fps.get(),
                          presentation_filter=presentation.get(), frame_rate=frame_rate.get(),
                          aspect_ratio=aspect.get())
            try:
                save_settings(self.state / "settings.json", values)
            except (OSError, ValueError) as exc:
                messagebox.showerror("Settings could not be saved", str(exc), parent=self.root)
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
        window.title("The Order: 1886 — Session log")
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
        self.log_text.insert("end", content or "No sessions recorded. Choose Verify files or Play to create a log.\n")
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
            save_settings(self.state / "settings.json", self.values)
            (self.state / "logs").mkdir(parents=True, exist_ok=True)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Cannot start session", str(exc), parent=self.root)
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
                        if code == 0 else f"Session failed (exit {code})")
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
                                self.detail = f"{report['missing_imports']} imports are unresolved. See View logs."
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
        if self.busy and not messagebox.askyesno("Stop current session?",
                "A session is running. Stop it and close the launcher?", parent=self.root):
            return
        if self.busy:
            self.closing = True
            self.stop()
        else:
            self.root.destroy()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--run-backend":
        attach_stdio()
        import order1886
        return order1886.main(argv[1:])
    parser = argparse.ArgumentParser(description="The Order: 1886 launcher")
    parser.add_argument("--state-dir", type=Path, default=STATE)
    parser.add_argument("--smoke-test", action="store_true", help="Open, render, check settings and close")
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
    import tkinter as tk
    root = tk.Tk()
    smoke_state = tempfile.TemporaryDirectory(prefix="order1886-launcher-smoke-") if args.smoke_test else None
    app = Launcher(root, Path(smoke_state.name) if smoke_state else args.state_dir.resolve())
    smoke_errors = []
    if args.smoke_test:
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        def smoke():
            try:
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
