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
                 "--frame-rate", str(values.get("frame_rate", 30))]
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
        self.menu_index = 0
        self.menu_items = []
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
        }
        if self.values["display_mode"] not in ("windowed", "borderless", "fullscreen"):
            self.values["display_mode"] = "borderless"
        if self.values["presentation_filter"] not in ("linear", "fsr1"):
            self.values["presentation_filter"] = "fsr1"
        if type(self.values["frame_rate"]) is not int or self.values["frame_rate"] not in (30, 60):
            self.values["frame_rate"] = 30
        root.title("The Order: 1886")
        root.configure(bg=BLACK)
        root.geometry("1160x700")
        root.minsize(940, 620)
        try:
            root.iconbitmap(str(ASSETS / "order1886.ico"))
        except tk.TclError:
            pass
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.canvas = tk.Canvas(root, bg=BLACK, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.backdrop = None
        self.icon_photo = None
        self.load_artwork()
        self.canvas.bind("<Configure>", self.resize)
        root.bind("<Up>", lambda e: self.move(-1))
        root.bind("<Down>", lambda e: self.move(1))
        root.bind("<Return>", self.activate)
        root.bind("<Escape>", self.back)
        self.status = "Experimental compatibility build"
        self.detail = "Gameplay and performance are not yet verified."
        self.refresh_status()
        root.after(100, self.poll)

    def load_artwork(self):
        """Read the player's own artwork at runtime; portable builds omit game art."""
        artwork = Path(self.values["game_dir"]) / "sce_sys"
        self.backdrop = None
        for path in (artwork / "pic0.png", ASSETS / "background.png"):
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
        w, h = max(c.winfo_width(), 940), max(c.winfo_height(), 620)
        panel = 430
        if self.backdrop:
            from PIL import ImageOps
            display = ImageOps.fit(self.backdrop, (w - panel, h),
                                   method=self.Image.Resampling.LANCZOS, centering=(.55, .5))
            self.background_photo = self.ImageTk.PhotoImage(display)
            c.create_image(panel, 0, image=self.background_photo, anchor="nw")
        c.create_rectangle(0, 0, panel, h, fill=BLACK, outline="")
        c.create_rectangle(panel, h - 72, w, h, fill=BLACK, outline="")
        c.create_text(52, 63, text="T H E   O R D E R", font=("Georgia", 23),
                      fill=GOLD, anchor="nw")
        c.create_text(54, 106, text="1 8 8 6", font=("Georgia", 16), fill=GOLD, anchor="nw")
        c.create_line(54, 149, 374, 149, fill="#4c432c")
        c.create_text(54, 169, text="PC LAUNCHER", font=("Georgia", 10), fill=MUTED, anchor="nw")
        actions = [("STOP SESSION" if self.busy else "PLAY", self.stop if self.busy else lambda: self.run("play")), ("SETTINGS", self.settings),
                   ("VERIFY FILES", lambda: self.run("verify")),
                   ("VIEW LOGS", self.show_logs), ("EXIT", self.close)]
        self.menu_items = []
        for index, (label, action) in enumerate(actions):
            y = 255 + index * 49
            tag = f"menu{index}"
            c.create_rectangle(46, y - 9, 383, y + 32, fill=BLACK, outline="", tags=(tag,))
            item = c.create_text(55, y, text=label, fill=GOLD if index == self.menu_index else PAPER,
                                 font=("Georgia", 17 if index == self.menu_index else 15),
                                 anchor="nw", tags=(tag,))
            c.tag_bind(tag, "<Enter>", lambda e, i=index: self.select(i))
            c.tag_bind(tag, "<Button-1>", lambda e, i=index: self.click(i))
            self.menu_items.append((item, action))
        c.create_text(54, h - 121, text=self.status, fill=GOLD, font=("Segoe UI", 10),
                      anchor="nw", width=325, tags="status")
        detail = self.detail if len(self.detail) <= 110 else self.detail[:107] + "…"
        c.create_text(54, h - 94, text=detail, fill=MUTED, font=("Segoe UI", 9),
                      anchor="nw", width=330, tags="detail")
        c.create_text(54, h - 29, text="↑ ↓  Navigate       Enter  Select       Esc  Back",
                      fill=MUTED, font=("Segoe UI", 9), anchor="w")
        c.create_text(w - 28, h - 33, text="THE ORDER: 1886", fill=MUTED,
                      font=("Georgia", 10), anchor="e")
        self.select(self.menu_index)

    def select(self, index):
        if self.settings_frame:
            return
        self.menu_index = index
        for i, (item, _) in enumerate(self.menu_items):
            self.canvas.itemconfigure(item, fill=GOLD if i == index else PAPER,
                                      font=("Georgia", 17 if i == index else 15))
        self.canvas.delete("selection")
        y = 255 + index * 49
        self.canvas.create_line(54, y - 5, 153, y - 5, fill=GOLD, tags="selection")
        self.canvas.create_line(54, y + 28, 153, y + 28, fill=GOLD, tags="selection")

    def move(self, direction):
        if not self.settings_frame:
            self.select((self.menu_index + direction) % 5)

    def activate(self, event=None):
        if not self.settings_frame and self.menu_items:
            self.menu_items[self.menu_index][1]()

    def click(self, index):
        self.select(index)
        self.activate()

    def back(self, event=None):
        if self.settings_frame:
            self.settings_frame.destroy()
            self.settings_frame = None
            self.root.focus_set()

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
        tk = self.tk
        container = self.settings_frame = tk.Frame(self.root, bg=BLACK)
        container.place(x=430, y=0, relwidth=1, width=-430, relheight=1)
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
                          presentation_filter=presentation.get(), frame_rate=frame_rate.get())
            try:
                save_settings(self.state / "settings.json", values)
            except (OSError, ValueError) as exc:
                messagebox.showerror("Settings could not be saved", str(exc), parent=self.root)
                return
            self.values = values
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
                app.move(1)
                app.move(-1)
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
