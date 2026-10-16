#!/usr/bin/env python3
"""CPU-only checks of a clean portable package, from a new path with spaces."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="Clean The Order 1886 package folder")
    parser.add_argument("--game-dir", type=Path, help="Optional existing game; prepare-only never enters the game")
    parser.add_argument("--output", type=Path, default=Path("out/order1886-evidence"))
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("This verification requires Windows")
    package = args.package.resolve()
    if (package / "user").exists():
        parser.error("Use a clean package, before player state has been created inside it")
    work = args.output.resolve() / ("Portable Smoke " + uuid.uuid4().hex[:10])
    copied = work / "The Order 1886"
    shutil.copytree(package, copied)
    report = {"scope": "Host bootstrap, GUI and preparation only; gameplay remains unverified.",
              "package": str(package), "tested_copy": str(copied), "checks": {}}
    report_path = work / "smoke-report.json"
    manifest = json.loads((copied / "package-manifest.json").read_text(encoding="utf-8-sig"))
    expected_scripts = {"prepare.py", "link_modules.py", "link_libc.py", "save_backup.py"}
    actual_scripts = {p.name for p in (copied / "_internal/scripts").iterdir()}
    expected_art = {"order1886.ico", "ARTWORK.txt"}
    actual_art = {p.name for p in (copied / "_internal/launcher/order1886").iterdir()}
    mismatches = [item["path"] for item in manifest["files"]
                  if sha256(copied / item["path"]) != item["sha256"]]
    report["checks"]["manifest"] = {"passed": not mismatches, "mismatches": mismatches}
    report["checks"]["preparation_closure"] = {"passed": actual_scripts == expected_scripts,
                                                   "files": sorted(actual_scripts)}
    report["checks"]["artwork"] = {"passed": actual_art == expected_art, "files": sorted(actual_art)}
    runtime = copied / "bin/order1886-runtime.exe"
    identity = json.loads((runtime.parent / "runtime-build.json").read_text(encoding="utf-8-sig"))
    report["runtime_sha256"] = sha256(runtime)
    report["checks"]["runtime_identity"] = {"passed":
        identity.get("runtime_sha256") == report["runtime_sha256"] == manifest["runtime_sha256"]
        and identity.get("runtime_abi") == "order1886-native-1"
        and identity.get("game_profile") == "order1886", "identity": identity}
    # Deliberately omit developer Python, compiler and dependency directories.
    env = {name: value for name, value in os.environ.items() if name.upper() in
           {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "SYSTEMDRIVE"}}
    env["PATH"] = str(runtime.parent) + os.pathsep + str(Path(os.environ["SystemRoot"]) / "System32")
    report["tested_PATH"] = env["PATH"]
    cwd = work / "Different Working Directory"
    cwd.mkdir()
    launcher = copied / "The Order 1886.exe"
    state = copied / "user/order1886"

    def run(name, command, expected, timeout=45):
        started = time.monotonic()
        try:
            result = subprocess.run([str(x) for x in command], cwd=cwd, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace", timeout=timeout)
            output, code = result.stdout, result.returncode
        except subprocess.TimeoutExpired as exc:
            output, code = f"Timed out after {timeout} seconds: {exc}", None
        log = work / (name + ".log")
        log.write_text(output, encoding="utf-8")
        report["checks"][name] = {"passed": code in expected, "exit_code": code,
                                  "elapsed_seconds": round(time.monotonic() - started, 3),
                                  "command": [str(x) for x in command], "log": str(log)}
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    run("native_help", [runtime, "--help"], {0, 2})
    run("native_info", [runtime, "--runtime-info"], {0})
    run("gui", [launcher, "--state-dir", state, "--smoke-test"], {0})
    run("missing_game", [launcher, "--run-backend", "--game-dir", work / "Missing Game",
                         "--state-dir", state], {2})
    if args.game_dir:
        run("prepare", [launcher, "--run-backend", "--game-dir", args.game_dir.resolve(),
                        "--state-dir", state, "--prepare-only"], {0}, timeout=300)
        image = state / "prepared/boot-linked.bin"
        with image.open("rb") as stream:
            header = stream.read(8).decode("ascii", errors="replace")
        report["checks"]["prepared_format"] = {"passed": header == "PS4BOOT5", "header": header}
    report["passed"] = all(item["passed"] for item in report["checks"].values())
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(report_path)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
