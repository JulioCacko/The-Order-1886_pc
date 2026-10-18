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
import struct
import time
import uuid


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="Clean The Order 1886 package folder")
    parser.add_argument("--game-dir", type=Path,
                        help="Optional verified game build; CPU-only 30/experimental-60 preparation")
    parser.add_argument("--output", type=Path, default=Path("out/order1886-evidence"))
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("This verification requires Windows")
    package = args.package.resolve()
    if (package / "user").exists():
        parser.error("Use a clean package, before player state has been created inside it")
    work = args.output.resolve() / ("Portable Smoke ç ' " + uuid.uuid4().hex[:10])
    copied = work / "The Order 1886"
    shutil.copytree(package, copied)
    report = {"scope": "Host bootstrap, GUI and preparation only; gameplay remains unverified.",
              "package": str(package), "tested_copy": str(copied), "checks": {}}
    report_path = work / "smoke-report.json"
    manifest = json.loads((copied / "package-manifest.json").read_text(encoding="utf-8-sig"))
    expected_scripts = {"prepare.py", "link_modules.py", "link_libc.py", "save_backup.py", "order1886_frame_rate.py", "order1886_display.py", "order1886_cache.py", "order1886_steam.py", "order1886_mods.py"}
    actual_scripts = {p.name for p in (copied / "_internal/scripts").iterdir()}
    expected_art = {"order1886.ico", "ARTWORK.txt", "launcher-art.jpg", "launcher-art.png", "launcher-art.txt",
                    "play-brass.png", "logo-horizontal.png", "logo-stacked.png", "app-icon.png", "BRANDING.txt"}
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
    quick_play = copied / "Play The Order 1886.exe"
    report["checks"]["quick_play_executable"] = {
        "passed": quick_play.is_file() and sha256(quick_play) == sha256(launcher)}
    state = copied / "user/order1886"

    def run(name, command, expected, timeout=45, without_stdio=False):
        started = time.monotonic()
        try:
            if without_stdio:
                import _winapi
                startup = subprocess.STARTUPINFO()
                startup.dwFlags = subprocess.STARTF_USESTDHANDLES | subprocess.STARTF_USESHOWWINDOW
                startup.wShowWindow = 0
                startup.hStdInput = startup.hStdOutput = startup.hStdError = 0
                process, thread, _, _ = _winapi.CreateProcess(
                    None, subprocess.list2cmdline([str(x) for x in command]), None, None, False,
                    subprocess.CREATE_NO_WINDOW, env, str(cwd), startup)
                try:
                    if _winapi.WaitForSingleObject(process, int(timeout * 1000)) == _winapi.WAIT_TIMEOUT:
                        _winapi.TerminateProcess(process, 1)
                        _winapi.WaitForSingleObject(process, 5000)
                        raise subprocess.TimeoutExpired(command, timeout)
                    output, code = "", _winapi.GetExitCodeProcess(process)
                finally:
                    _winapi.CloseHandle(thread)
                    _winapi.CloseHandle(process)
            else:
                result = subprocess.run([str(x) for x in command], cwd=cwd, env=env,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace", timeout=timeout,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
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
    run("quick_play_setup_gui", [quick_play, "--state-dir", state, "--smoke-test"], {0})
    run("missing_game", [launcher, "--run-backend", "--game-dir", work / "Missing Game",
                         "--state-dir", state], {2})
    detached_state = work / "No standard handles state"
    run("missing_game_without_stdio", [launcher, "--run-backend", "--game-dir", work / "Missing Game",
                                      "--state-dir", detached_state], {2}, without_stdio=True)
    diagnostic = detached_state / "logs/backend.log"
    detached = report["checks"]["missing_game_without_stdio"]
    detached["diagnostic_log"] = str(diagnostic)
    detached["passed"] = detached["passed"] and diagnostic.is_file() and \
        "Missing or empty game file:" in diagnostic.read_text(encoding="utf-8")
    if args.game_dir:
        original_eboot = args.game_dir.resolve() / 'eboot.bin'
        original_eboot_sha256 = sha256(original_eboot)
        run("prepare", [launcher, "--run-backend", "--game-dir", args.game_dir.resolve(),
                        "--state-dir", state, "--prepare-only"], {0}, timeout=300)
        image = state / "prepared/boot-linked.bin"
        with image.open("rb") as stream:
            header = stream.read(8).decode("ascii", errors="replace")
        report["checks"]["prepared_format"] = {"passed": header == "PS4BOOT5", "header": header}
        experimental_state = work / 'Experimental 60 state'
        run('experimental_60_prepare', [launcher, '--run-backend', '--game-dir', args.game_dir.resolve(),
                                       '--state-dir', experimental_state, '--prepare-only', '--frame-rate', '60'],
            {0}, timeout=300)
        check = report['checks']['experimental_60_prepare']
        check['original_eboot_preserved'] = sha256(original_eboot) == original_eboot_sha256
        try:
            prepared = experimental_state / 'prepared'
            timing_profile = json.loads((prepared / 'prepared.json').read_text())['frame_rate_profile']
            with (prepared / 'boot.bin').open('rb') as stream:
                magic, size, entry, ns, nr, ni, flags = struct.unpack('<8s6Q', stream.read(56))
                stream.seek(56 + ns * 24 + ni * 128 + nr * 32 + 0x4507be)
                instruction = stream.read(10).hex()
            check.update(frame_rate_profile=timing_profile, instruction_after=instruction,
                         warning_present='Chapters 6 and 9' in Path(check['log']).read_text(encoding='utf-8'))
            check['passed'] = check['passed'] and check['original_eboot_preserved'] and \
                timing_profile.get('source_verified') is True and timing_profile.get('applied') is True and \
                timing_profile.get('engine_fps') == 60 and timing_profile.get('host_fps_limit') == 60 and \
                instruction == 'c7058c05170101000000' and magic == b'PS4BOOT2' and check['warning_present']
        except (OSError, ValueError, KeyError, struct.error) as error:
            check.update(passed=False, error=str(error))
    if args.game_dir:
        quick_state = work / "Quick saved state"
        quick_state.mkdir()
        settings = {
            "game_dir": str(args.game_dir.resolve()), "runtime": "",
            "display_mode": "windowed", "vsync": False, "show_fps": True,
            "presentation_filter": "linear", "frame_rate": 30, "aspect_ratio": "original",
            "mouse_look": False, "mouse_sensitivity": 175, "mouse_invert_y": True,
        }
        (quick_state / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        quick_log = work / "quick_play_saved.log"
        check = {"passed": False}
        try:
            with quick_log.open("w", encoding="utf-8") as output:
                process = subprocess.Popen([str(quick_play), "--state-dir", str(quick_state)],
                    cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=output,
                    stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
                try:
                    deadline = time.monotonic() + 30
                    command = ""
                    while time.monotonic() < deadline and process.poll() is None:
                        logs = list(quick_state.glob("launcher-*.log"))
                        if logs:
                            command = logs[0].read_text(encoding="utf-8", errors="replace")
                            import re
                            token = re.search(r"session-stop-[0-9a-f]{32}", command)
                            if token:
                                (quick_state / token.group()).touch()
                                break
                        time.sleep(0.05)
                    code = process.wait(timeout=30)
                    expected = ("--display-mode windowed", "--presentation-filter linear",
                                "--frame-rate 30", "--aspect-ratio original", "--vsync 0",
                                "--mouse-look 0", "--mouse-sensitivity 175", "--mouse-invert-y 1")
                    check.update(passed=code in (0, 130) and all(part in command for part in expected),
                                 exit_code=code, command_log=command, log=str(quick_log))
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
        except (OSError, subprocess.SubprocessError) as error:
            check["error"] = str(error)
        report["checks"]["quick_play_saved_settings"] = check
    report["passed"] = all(item["passed"] for item in report["checks"].values())
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(report_path)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
