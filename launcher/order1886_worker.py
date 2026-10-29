#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Allowlisted JSON-lines adapter for the Go launcher and existing Order helpers."""
from __future__ import annotations

import argparse
import contextlib
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
from launcher import order1886_common as legacy
from launcher.order1886_lang import LANGUAGES, table
from launcher.order1886_options import FIELDS, PAGES

MAX_REQUEST = 64 * 1024
METHODS = frozenset(("state.get", "settings.set", "settings.reset", "session.start", "session.stop",
                     "saves.list", "saves.backup", "saves.restore", "saves.import", "cache.clear", "mods.list",
                     "steam.add", "shortcut.create", "updates.preflight", "performance.report",
                     "patches.list", "patches.apply"))
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
            if value % item.get("multiple", 1):
                raise ValueError(f'{item["label"]} must be a multiple of {item["multiple"]}.')
        elif kind in ("directory", "file", "text"):
            if not isinstance(value, str) or len(value) > 4096 or any(c in value for c in ("\0", "\r", "\n")):
                raise ValueError(item["label"] + " must be a valid path or text.")
        elif kind == "secret":
            from scripts.order1886_trophy_text import parse_key
            if not isinstance(value, str):
                raise ValueError(item["label"] + " must be text.")
            parse_key(value)
        elif kind == "order":
            order1886.mods.validate_config(Path("."), False, value)
        elif kind == "patches":
            from scripts.order1886_patches import validate_selection
            validate_selection(value)
        elif kind == "bindings":
            order1886.inputs.validate(value, item["input_kind"])


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
        self._state_locked = False
        # Legacy helper defaults remain unchanged; explicit installation/state paths
        # support both source runs and a worker under the portable bin directory.
        legacy.ROOT = self.installation
        order1886.INSTALL_ROOT = self.installation

    @contextlib.contextmanager
    def state_lock(self):
        """Hold the player-session lock for a state write, once per nested use.

        `require_idle` only sees this worker's own sessions; the OS lock is the only thing that
        also excludes a direct-play game or another launcher. Reentrancy keeps a caller already
        inside the lock from deadlocking on a second handle.
        """
        if self._state_locked:
            yield
            return
        self.state.mkdir(parents=True, exist_ok=True)
        with order1886.session_lock(self.state):
            self._state_locked = True
            try:
                yield
            finally:
                self._state_locked = False

    def settings(self):
        defaults = legacy.load_launch_settings(self.state, {})
        values = {**defaults, **legacy.read_settings(self.state / "settings.json")}
        # A change made in the in-game menu lives in runtime.ini; adopt it once so both
        # surfaces agree instead of the next Play silently discarding it.
        imported = order1886.menu_settings_import(self.state, values)
        if imported:
            values.update(imported)
            with self.state_lock():
                legacy.save_settings(self.state / "settings.json", values)
        return values

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
            for candidate in ("selective", "precise", "performance_capture", "htile_control",
                              "effect_toggles"):
                try:
                    if candidate == "performance_capture":
                        order1886.validate_performance_capture(runtime, True)
                    elif candidate == "htile_control":
                        order1886.validate_htile_control(runtime, True)
                    elif candidate == "effect_toggles":
                        order1886.validate_effect_toggle_support(runtime)
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
        try:
            runtime = order1886.find_runtime(values.get("runtime") or None)
            if runtime is None:
                raise ValueError("Select a verified native runtime to choose custom inputs.")
            input_catalog, input_reason = order1886.input_catalog(runtime), ""
        except (OSError, ValueError) as exc:
            input_catalog, input_reason = None, str(exc)
        for item in fields:
            if item["kind"] == "bindings":
                item["reason"] = input_reason
                if input_catalog is not None:
                    kind = item["input_kind"]
                    defaults = {row["id"]: row[kind + "_default"] for row in input_catalog["buttons"]}
                    for button in item["buttons"]:
                        button["default"] = defaults[button["id"]]
                    item["choices"] = [{"value": name, "label": name,
                                        "available": not bool(order1886.inputs.source_reason(name, kind)),
                                        "reason": order1886.inputs.source_reason(name, kind)}
                                       for name in input_catalog[kind + "_sources"]]
                    item["choices"].insert(0, {"value": order1886.inputs.UNBOUND,
                                               "label": "No digital source", "available": True, "reason": ""})
                try:
                    order1886.inputs.validate(values.get(item["key"], {}), item["input_kind"], input_catalog)
                except ValueError as exc:
                    item["reason"] = "Saved bindings need attention: " + str(exc) + " Reset this section or replace invalid inputs."
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
            experimental = order1886.editions.experimental(metadata["TITLE_ID"])
            readiness = {"ready": True, "metadata": metadata, "experimental": experimental,
                         "message": "Game files found (experimental edition)" if experimental else "Game files found"}
        except (OSError, ValueError) as exc:
            readiness = {"ready": False, "message": str(exc), "metadata": {}, "experimental": False}
        from scripts import order1886_trophy_history
        trophy_error = ""
        try:
            trophies = order1886_trophy_history.read(
                self.state, readiness["metadata"].get("TITLE_ID", order1886.TITLE_ID))
        except (OSError, ValueError) as exc:
            trophies, trophy_error = [], str(exc)
        trophy_catalog, trophy_catalog_error = [], ""
        if readiness["ready"]:
            earned = {row["id"] for row in trophies}
            try:
                trophy_catalog = order1886_trophy_history.catalog(game, earned)
            except (OSError, ValueError) as exc:
                trophy_catalog_error = "Installed achievement artwork is unavailable: " + str(exc)
            # Names and descriptions come from the player's own game, decrypted with the trophy
            # key they entered (shadPS4's method). Hidden trophies stay secret until earned.
            try:
                language = order1886.SYSTEM_LANGUAGES.get(values.get("ui_language", "en"), 1)
                text = order1886_trophy_history.catalog_text(game, values.get("trophy_key", ""), language)
            except (OSError, ValueError, ImportError) as exc:
                text, trophy_catalog_error = {}, "Trophy names are unavailable: " + str(exc)
            for row in trophy_catalog:
                info = text.get(row["id"])
                if info:
                    secret = info["hidden"] and row["id"] not in earned
                    row.update(grade=info["grade"], hidden=info["hidden"],
                               name="" if secret else info["name"], detail="" if secret else info["detail"])
        else:
            trophy_catalog_error = "Select a valid game folder to show installed achievement artwork."
        return {"version": 1, "settings": values, "fields": fields, "pages": PAGES,
                "trophies": trophies, "trophy_error": trophy_error,
                "trophy_catalog": trophy_catalog, "trophy_catalog_error": trophy_catalog_error,
                "languages": LANGUAGES, "translations": table(values.get("ui_language", "en")),
                "game": readiness, "state_dir": str(self.state), "installation": str(self.installation),
                "busy": self.busy, "logfile": str(self.logfile) if self.logfile else "",
                "last_exit": self.last_exit, "logs": self.log_tail[-100:],
                "timing": self.timing(values),
                "patches": self.patch_catalogue(values),
                "backups": order1886.save_backup.list_backups(self.state),
                "saves_dir": str(self.state / "savedata"),
                "acceptance": "Development preview — gold gameplay and provider qualification remain open."}

    def patch_catalogue(self, values):
        """Catalogue rows the launcher shows: the built-ins point at their own settings."""
        from scripts.order1886_patches import BUILTIN_IDS, RECIPES, identity_error
        try:
            metadata = order1886.inspect_game(Path(values.get("game_dir") or "."))
        except (OSError, ValueError):
            metadata = None
        rows = []
        for item in RECIPES:
            builtin = item["id"] in BUILTIN_IDS
            if builtin:
                reason = "Configured by the game frame rate or framing setting, not by a patch selection."
            elif metadata is None:
                reason = "Select a valid game folder to check this recipe."
            else:
                reason = identity_error(item, metadata) or ""
            rows.append({"id": item["id"], "title": item["title"],
                         "description": item["description"], "builtin": builtin,
                         "available": not reason and not builtin, "reason": reason,
                         "warning": item.get("warning", "")})
        return rows
    def timing(self, values):
        """Report engine rate, presentation cadence, host cap and VSync as resolved."""
        try:
            return order1886.timing_profile(values)
        except ValueError as exc:
            return {"error": str(exc)}

    def game_folder(self):
        """The selected game folder, resolved the way every other worker path is."""
        game = Path(self.settings().get("game_dir") or order1886.default_game_dir())
        return (game if game.is_absolute() else self.installation / game).resolve()

    def guest_executable(self, game):
        """The selected executable's bytes and metadata, or a reason they are unavailable."""
        try:
            metadata = order1886.inspect_game(game)
            executable = (game / "eboot.bin").read_bytes()
        except (OSError, ValueError) as exc:
            return {}, b"", str(exc)
        return metadata, executable, ""

    def list_patches(self):
        """Every version-checked recipe with its applicability; reads, never writes."""
        from scripts import order1886_patches as catalogue
        game = self.game_folder()
        metadata, executable, problem = self.guest_executable(game)
        recipes = ([catalogue.describe(item, problem) for item in catalogue.RECIPES] if problem
                   else catalogue.catalogue(executable, metadata))
        return {"recipes": recipes, "game": {"ready": not problem, "folder": str(game),
                                             "message": problem or "Game files found",
                                             "metadata": metadata}}

    def apply_patch(self, params):
        """Derive a patched copy of the selected executable; the game folder is only read."""
        self.confirm(params)
        from scripts import order1886_patches as recipes
        identifier = params.get("id")
        if not isinstance(identifier, str):
            raise ValueError("Provide the id of a patch recipe to apply.")
        recipe = recipes.recipe(identifier)
        self.safe_state()
        game = self.game_folder()
        metadata, executable, problem = self.guest_executable(game)
        if problem:
            raise ValueError(problem)
        destination = (self.state / "patched" / (recipe["id"] + ".bin")).resolve()
        if destination == game or game in destination.parents:
            raise ValueError("A derived patch image belongs outside the selected game folder.")
        with self.state_lock():
            return recipes.apply_recipe_bytes(recipe, recipes.decode(recipe, executable),
                                              destination, metadata)

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

    def report(self, params):
        """Summarize this state's newest frame traces. Read-only, and it decides nothing."""
        from scripts import order1886_perf_report as perf
        count = params.get("count", 1)
        if type(count) is not int or not 1 <= count <= perf.MAX_TRACES:
            raise ValueError("A performance report reads between 1 and %d recordings at a time."
                             % perf.MAX_TRACES)
        logs = self.state / "logs"
        paths = sorted(logs.glob("performance-*.csv"),
                       key=lambda path: path.stat().st_mtime_ns, reverse=True)
        if not paths:
            raise ValueError("No performance recording found: %s holds no performance-*.csv. "
                             "Turn on System > Record performance data, play the scene, and quit the "
                             "game normally so the trace is closed." % logs)
        return perf.summarize(paths[:count])

    def dispatch(self, method, params):
        if method not in METHODS:
            raise ValueError("Unknown worker method.")
        if not isinstance(params, dict):
            raise ValueError("Request params must be an object.")
        if method == "state.get":
            return self.snapshot()
        if method == "performance.report":
            return self.report(params)
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
        if method == "patches.list":
            return self.list_patches()
        self.require_idle()
        if method == "patches.apply":
            return self.apply_patch(params)
        if method == "updates.preflight":
            self.safe_state()
            self.state.mkdir(parents=True, exist_ok=True)
            # The helper must reacquire and hold this lock across replacement.
            with order1886.session_lock(self.state):
                return {"ready": True}
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
            mapping_keys = {kind + '_bindings' for kind in ('keyboard', 'controller')}
            if mapping_keys & patch.keys() or 'runtime' in patch:
                selected = {key: values.get(key, {}) for key in mapping_keys
                            if key in patch or 'runtime' in patch}
                runtime = order1886.find_runtime(values.get('runtime') or None) if any(selected.values()) else None
                order1886.validate_input_settings(runtime, selected)
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
            if ({"runtime", "htile_unqualified"} & patch.keys() and
                    values.get("htile_unqualified")):
                reason = self.native_option_reason(values, "htile_control")
                if reason:
                    raise ValueError(reason)
            if ({"runtime", "synchronous_recording", "texture_update_locking"} & patch.keys() and
                    (values.get("synchronous_recording") or values.get("texture_update_locking"))):
                reason = self.native_option_reason(values, "effect_toggles")
                if reason:
                    raise ValueError(reason)
            order1886.mods.validate_config(order1886.mods.resolve_root(values.get("mods_dir", ""), self.installation),
                                          values.get("mods_enabled", False), values.get("mod_order", []))
            with self.state_lock():
                legacy.save_settings(self.state / "settings.json", values)
            return self.snapshot()
        if method == "saves.restore":
            self.confirm(params)
            self.restore(params.get("name", ""))
        elif method == "saves.import":
            self.confirm(params)
            self.safe_state()
            source = params.get("path")
            if not isinstance(source, str) or not source:
                raise ValueError("Choose the folder that holds the saves to import.")
            self.state.mkdir(parents=True, exist_ok=True)
            with order1886.session_lock(self.state):
                order1886.save_backup.import_saves(self.state, source)
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
            except Exception as exc:  # noqa: BLE001 - a bug in one method must not end the session
                # Anything else is a defect inside a method. Answering with an error keeps the
                # launcher usable and its session stoppable; exiting here would look like a
                # lost worker while the game may still be running.
                import traceback
                traceback.print_exc()
                send({"version": 1, "id": request_id,
                      "error": {"message": f"{type(exc).__name__}: {exc}"}})
    finally:
        worker.close()


def frozen_installation_root(executable):
    """The package folder of a frozen worker: bin/order1886-worker.exe on Windows, and on Linux
    PyInstaller's one-directory bin/order1886-worker/order1886-worker (launcher-go pkgpath.Worker)."""
    folder = executable.parent
    return folder.parent.parent if folder.name == "order1886-worker" else folder.parent


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--run-backend":
        if getattr(sys, "frozen", False):
            order1886.INSTALL_ROOT = frozen_installation_root(Path(sys.executable).resolve())
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

