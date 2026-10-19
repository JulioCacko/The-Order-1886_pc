#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Allowlisted JSON-lines adapter for the Go launcher and existing Order helpers."""
from __future__ import annotations

import argparse
import copy
import io
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid

PROJECT_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
import order1886
from launcher import order1886_launcher as legacy
from launcher.order1886_lang import LANGUAGES, table
from launcher.order1886_options import FIELDS, PAGES

MAX_REQUEST = 64 * 1024
METHODS = frozenset(("state.get", "settings.set", "settings.reset", "session.start", "session.stop",
                     "saves.list", "saves.backup", "saves.restore", "cache.clear", "mods.list",
                     "steam.add", "shortcut.create"))
FIELD_BY_KEY = {item["key"]: item for item in FIELDS}


def validate_patch(values):
    if not isinstance(values, dict) or not values:
        raise ValueError("Provide a non-empty settings object.")
    for key, value in values.items():
        item = FIELD_BY_KEY.get(key)
        if item is None:
            raise ValueError("Unknown player setting: " + str(key))
        if not item["available"]:
            raise ValueError(item["label"] + ": " + item["reason"])
        kind = item["kind"]
        if kind == "select":
            choice = next((c for c in item["choices"] if type(c["value"]) is type(value) and c["value"] == value), None)
            if choice is None or not choice["available"]:
                raise ValueError(item["label"] + ": " + (choice["reason"] if choice else "unsupported value"))
        elif kind == "boolean" and type(value) is not bool:
            raise ValueError(item["label"] + " must be a boolean.")
        elif kind == "number":
            if type(value) is not int or not item["minimum"] <= value <= item["maximum"]:
                raise ValueError(item["label"] + " is outside the supported range.")
        elif kind in ("directory", "file", "text"):
            if not isinstance(value, str) or len(value) > 4096 or any(c in value for c in ("\0", "\r", "\n")):
                raise ValueError(item["label"] + " must be a valid path or text.")
        elif kind == "order":
            order1886.mods.validate_config(Path("."), False, value)


class Worker:
    def __init__(self, state: Path, installation: Path, emit=None):
        self.state = Path(state).absolute()
        self.installation = Path(installation).resolve()
        self.emit = emit or (lambda event, data: None)
        self.thread = None
        self.cancelled = threading.Event()
        self.stop_file = None
        self.busy = False
        self.logfile = None
        self.last_exit = None
        self.log_tail = []
        self._runtime_support = None
        # Legacy helper defaults remain unchanged; explicit installation/state paths
        # support both source runs and a worker under the portable bin directory.
        legacy.ROOT = self.installation
        order1886.INSTALL_ROOT = self.installation

    def settings(self):
        defaults = legacy.load_launch_settings(self.state, {})
        return {**defaults, **legacy.read_settings(self.state / "settings.json")}

    def readback_policy_reason(self, values, policy):
        return self.native_option_reason(values, policy)

    def native_option_reason(self, values, option):
        requested = values.get("runtime", "")
        def signature(runtime):
            receipt = runtime.with_name("runtime-build.json")
            return tuple((p.stat().st_size, p.stat().st_mtime_ns)
                         for p in (runtime, receipt)) + (order1886.sha256(receipt),)
        try:
            runtime = order1886.find_runtime_path(requested or None)
            if runtime is None:
                return "Select a verified native runtime declaring support for this option first."
            stamp = signature(runtime)
            if self._runtime_support is not None:
                previous, previous_runtime, previous_stamp, reasons = self._runtime_support
                if requested == previous and runtime == previous_runtime and previous_stamp == stamp:
                    return reasons[option]
            order1886.find_runtime(runtime)
            reasons = {}
            for candidate in ("selective", "precise", "performance_capture"):
                try:
                    if candidate == "performance_capture":
                        order1886.validate_performance_capture(runtime, True)
                    else:
                        order1886.validate_readback_policy(runtime, candidate)
                    reasons[candidate] = ""
                except ValueError as exc:
                    reasons[candidate] = str(exc)
            if signature(runtime) != stamp:
                return "Runtime files changed while checking options. Try again."
            self._runtime_support = requested, runtime, stamp, reasons
            return reasons[option]
        except (OSError, ValueError) as exc:
            return "This runtime option is unavailable: " + str(exc)

    def snapshot(self):
        values = self.settings()
        fields = copy.deepcopy(FIELDS)
        for item in fields:
            if item["key"] == "performance_capture":
                reason = self.native_option_reason(values, "performance_capture")
                item.update(available=not bool(reason) or values.get("performance_capture") is True,
                            reason=reason)
            if item["key"] == "readbacks":
                for choice in item["choices"]:
                    if choice["value"] in ("selective", "precise"):
                        reason = self.readback_policy_reason(values, choice["value"])
                        choice.update(available=not bool(reason), reason=reason)
        game = Path(values.get("game_dir") or order1886.default_game_dir())
        if not game.is_absolute():
            game = self.installation / game
        try:
            metadata = order1886.inspect_game(game)
            readiness = {"ready": True, "message": "Game files found", "metadata": metadata}
        except (OSError, ValueError) as exc:
            readiness = {"ready": False, "message": str(exc), "metadata": {}}
        from scripts import order1886_trophy_history
        trophy_error = ""
        try:
            trophies = order1886_trophy_history.read(self.state)
        except (OSError, ValueError) as exc:
            trophies, trophy_error = [], str(exc)
        trophy_catalog, trophy_catalog_error = [], ""
        if readiness["ready"]:
            try:
                trophy_catalog = order1886_trophy_history.catalog(game, {row["id"] for row in trophies})
            except (OSError, ValueError) as exc:
                trophy_catalog_error = "Installed achievement artwork is unavailable: " + str(exc)
        else:
            trophy_catalog_error = "Select a valid game folder to show installed achievement artwork."
        return {"version": 1, "settings": values, "fields": fields, "pages": PAGES,
                "trophies": trophies, "trophy_error": trophy_error,
                "trophy_catalog": trophy_catalog, "trophy_catalog_error": trophy_catalog_error,
                "languages": LANGUAGES, "translations": table(values.get("ui_language", "en")),
                "game": readiness, "state_dir": str(self.state), "installation": str(self.installation),
                "busy": self.busy, "logfile": str(self.logfile) if self.logfile else "",
                "last_exit": self.last_exit, "logs": self.log_tail[-100:],
                "backups": order1886.save_backup.list_backups(self.state),
                "acceptance": "Development preview — gold gameplay and provider qualification remain open."}

    def require_idle(self):
        if self.busy:
            raise ValueError("Stop the current session before changing settings or player data.")

    def confirm(self, params):
        if params.get("confirmed") is not True:
            raise ValueError("This operation requires explicit confirmation.")

    def safe_state(self):
        game = Path(self.settings()["game_dir"])
        game = (game if game.is_absolute() else self.installation / game).resolve()
        state = self.state.resolve()
        if state == game or game in state.parents:
            raise ValueError("Launcher state must be outside the selected game folder.")

    def restore(self, name):
        self.safe_state()
        self.state.mkdir(parents=True, exist_ok=True)
        with order1886.session_lock(self.state):
            return order1886.save_backup.restore(self.state, name)

    def put(self, event):
        kind, data = event
        if kind == "line":
            if len(data) > 2048:
                data = data[:2048] + "\n[Full output is retained in the session log.]\n"
            self.log_tail.append(data)
            self.log_tail = self.log_tail[-200:]
        elif kind == "done":
            self.last_exit = data[0]
            self.busy = False
        self.emit(kind, data)

    def start(self, params):
        self.require_idle()
        mode = params.get("mode", "play")
        if mode not in ("play", "verify", "prepare"):
            raise ValueError("Unsupported session mode.")
        backup = params.get("backup", "")
        if backup:
            if mode != "play":
                raise ValueError("Restore-on-Play is only available for a play session.")
            self.confirm(params)
        values = self.settings()
        validate_patch({key: value for key, value in values.items()
                        if key in FIELD_BY_KEY and FIELD_BY_KEY[key]["available"]})
        self.safe_state()
        if mode == "play":
            legacy.validate_launch_game(Path(values["game_dir"]), values)
        else:
            order1886.inspect_game(values["game_dir"])
        token = uuid.uuid4().hex
        stop = self.state / ("stop-" + token)
        command = legacy.backend_command(values, mode="play" if mode == "prepare" else mode,
                                         state=self.state, stop_file=stop)
        if mode == "prepare":
            command.append("--prepare-only")
        if backup:
            self.restore(backup)
        self.state.mkdir(parents=True, exist_ok=True)
        self.stop_file = stop
        self.logfile = self.state / ("launcher-" + time.strftime("%Y%m%d-%H%M%S") + "-" + token[:8] + ".log")
        self.cancelled = threading.Event()
        self.busy = True
        self.last_exit = None
        self.thread = threading.Thread(target=legacy.session_worker,
            args=(command, self.logfile, self, self.cancelled, stop, mode, self.installation), daemon=True)
        self.thread.start()
        return {"started": True, "logfile": str(self.logfile)}

    def dispatch(self, method, params):
        if method not in METHODS:
            raise ValueError("Unknown worker method.")
        if not isinstance(params, dict):
            raise ValueError("Request params must be an object.")
        if method == "state.get":
            return self.snapshot()
        if method == "session.start":
            return self.start(params)
        if method == "session.stop":
            self.cancelled.set()
            if self.busy and self.stop_file is not None:
                self.stop_file.touch()
            return {"stopping": self.busy}
        if method == "saves.list":
            return order1886.save_backup.list_backups(self.state)
        if method == "mods.list":
            values = self.settings()
            return order1886.mods.discover(order1886.mods.resolve_root(values.get("mods_dir", ""), self.installation))
        self.require_idle()
        if method in ("settings.set", "settings.reset"):
            patch = params.get("values")
            if method == "settings.reset":
                page = params.get("page")
                if page not in {p["id"] for p in PAGES}:
                    raise ValueError("Unknown settings page.")
                defaults = legacy.load_launch_settings(self.state, {})
                patch = {f["key"]: defaults.get(f["key"], f["default"]) for f in FIELDS
                         if f["page"] == page and f["available"]}
            validate_patch(patch)
            values = {**self.settings(), **patch}
            if ({"runtime", "readbacks"} & patch.keys() and
                    values.get("readbacks") in ("selective", "precise")):
                reason = self.readback_policy_reason(values, values["readbacks"])
                if reason:
                    raise ValueError(reason)
            if ({"runtime", "performance_capture"} & patch.keys() and
                    values.get("performance_capture")):
                reason = self.native_option_reason(values, "performance_capture")
                if reason:
                    raise ValueError(reason)
            order1886.mods.validate_config(order1886.mods.resolve_root(values.get("mods_dir", ""), self.installation),
                                          values.get("mods_enabled", False), values.get("mod_order", []))
            legacy.save_settings(self.state / "settings.json", values)
            return self.snapshot()
        if method == "saves.restore":
            self.confirm(params)
            self.restore(params.get("name", ""))
        elif method == "saves.backup":
            self.safe_state()
            self.state.mkdir(parents=True, exist_ok=True)
            with order1886.session_lock(self.state):
                if order1886.save_backup.backup(self.state) is None:
                    raise ValueError("No saves yet. Start a game and create a save first.")
        elif method == "cache.clear":
            self.confirm(params)
            self.safe_state()
            from scripts.order1886_cache import clear_shader_cache
            clear_shader_cache(self.state)
        elif method == "steam.add":
            from scripts.order1886_steam import add_to_steam
            return {"path": str(add_to_steam(self.installation, state=self.state))}
        elif method == "shortcut.create":
            return {"path": str(legacy.create_desktop_shortcut(self.installation))}
        return self.snapshot()

    def close(self):
        if self.busy:
            self.dispatch("session.stop", {})
            if self.thread:
                self.thread.join(timeout=15)


def serve(worker, source, output):
    lock = threading.Lock()

    def send(value):
        with lock:
            output.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
            output.flush()

    worker.emit = lambda event, data: send({"version": 1, "event": event, "data": data})
    try:
        while True:
            line = source.readline(MAX_REQUEST + 2)
            if not line:
                break
            request_id = None
            try:
                if len(line.encode("utf-8")) > MAX_REQUEST:
                    if not line.endswith("\n"):
                        while True:
                            tail = source.readline(MAX_REQUEST + 2)
                            if not tail or tail.endswith("\n"):
                                break
                    raise ValueError("Worker request exceeds 64 KiB.")
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("Request must be an object.")
                request_id = request.get("id")
                if (type(request_id) not in (str, int) or type(request.get("version")) is not int
                        or request["version"] != 1):
                    raise ValueError("Require protocol version 1 and a string or integer id.")
                result = worker.dispatch(request.get("method"), request.get("params", {}))
                send({"version": 1, "id": request_id, "result": result})
            except (ValueError, TypeError, OSError, RuntimeError) as exc:
                send({"version": 1, "id": request_id, "error": {"message": str(exc)}})
    finally:
        worker.close()


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--run-backend":
        if getattr(sys, "frozen", False):
            order1886.INSTALL_ROOT = Path(sys.executable).resolve().parent.parent
        return order1886.main(args[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--installation-root", type=Path, default=PROJECT_ROOT)
    options = parser.parse_args(args)
    if sys.stdout is None or sys.stdin is None:
        raise RuntimeError("The worker needs dedicated protocol pipes.")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    serve(Worker(options.state_dir, options.installation_root), sys.stdin, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

