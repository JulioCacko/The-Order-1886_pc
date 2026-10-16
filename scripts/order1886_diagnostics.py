"""Collect Order evidence without starting a game or changing its files.

The import table comes from the prepared PS4BOOT5 image. Source identities come
from the original SELF dynamic tables, never from an assumed library ID map.
Static shadPS4 registrations are reference evidence, not native runtime support.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent))
from link_modules import canonical, module  # noqa: E402


def file_identity(path):
    path = Path(path)
    result = {"path": str(path.resolve()), "exists": path.is_file()}
    if path.is_file():
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        result.update(bytes=path.stat().st_size, sha256=digest.hexdigest())
    return result


def prepared_imports(path):
    """Return exact import-table indices; reject malformed/truncated images."""
    with Path(path).open("rb") as source:
        header = source.read(56)
        if len(header) != 56:
            raise ValueError("truncated prepared image header")
        magic, size, entry, segments, relocs, count, flags = struct.unpack("<8s6Q", header)
        if magic != b"PS4BOOT5":
            raise ValueError("expected prepared PS4BOOT5 image")
        source.seek(96)  # header, process parameter, main TLS descriptor
        raw = source.read(8)
        if len(raw) != 8:
            raise ValueError("truncated module table")
        modules, = struct.unpack("<Q", raw)
        if max(modules, segments, count, relocs) > 1_000_000:
            raise ValueError("unreasonable prepared image table size")
        source.seek(56 * modules, 1)
        raw = source.read(8)
        if len(raw) != 8:
            raise ValueError("truncated binding table")
        bindings, = struct.unpack("<Q", raw)
        if bindings > 1_000_000:
            raise ValueError("unreasonable binding count")
        source.seek(bindings * 24 + segments * 24, 1)
        names = []
        for _ in range(count):
            raw = source.read(128)
            if len(raw) != 128 or b"\0" not in raw:
                raise ValueError("truncated or unterminated prepared import")
            names.append(raw.split(b"\0", 1)[0].decode("ascii"))
        if source.tell() + relocs * 32 + size != Path(path).stat().st_size:
            raise ValueError("prepared image size does not match its tables")
        return names


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run_observations(record_paths):
    observations = []
    for path in sorted(map(Path, record_paths)):
        record = read_json(path)
        log_path = Path(record.get("log", path.with_suffix(".log")))
        if not log_path.is_absolute():
            log_path = path.parent / log_path
        log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
        missing = sorted(set(re.findall(r"MISSING:\s+([^\s()]+#[^\s()]+)", log)))
        fatal = re.findall(r"first unsupported PS4 import:\s+(\S+)\s+\(index\s+(\d+)\)", log)
        observations.append({
            "record": file_identity(path), "log": file_identity(log_path),
            "mode": record.get("mode"), "runtime": record.get("runtime"),
            "runtime_sha256": record.get("runtime_sha256"),
            "build": record.get("build"),
            "image_sha256": record.get("image_sha256"),
            "started_utc": record.get("started_utc"), "exit_code": record.get("exit_code"),
            "runtime_exit_code": record.get("runtime_exit_code"),
            "timed_out": record.get("timed_out"), "status": record.get("status"),
            "stop_reason": record.get("stop_reason"),
            "reported_missing_import_count": record.get("missing_imports"),
            "settings": record.get("settings"), "elapsed_seconds": record.get("elapsed_seconds"),
            "commands": re.findall(r"^Command:\s*(.+)$", log, re.MULTILINE),
            "missing_imports": missing,
            "fatal_imports": [{"canonical": name, "index": int(index)} for name, index in fatal],
            "caller_addresses": re.findall(r"caller(?: return offset)?[=: ]+(0x[0-9a-fA-F]+)", log, re.I),
            "original_entry_observed": "Entering original x86-64 code" in log,
            "module_initializers": re.findall(r"^Module \d+ initializer returned .+$", log, re.MULTILINE),
            "runtime_counters": [line for line in log.splitlines() if line.startswith("Runtime:")],
            "shader_failures": [line for line in log.splitlines()
                                if re.search(r"shader|SPIR-V|pipeline", line, re.I)
                                and re.search(r"error|fail|unsupported|assert", line, re.I)],
            "graphics_initialization": [line for line in log.splitlines()
                                        if "presenter ready" in line or "GPU: using" in line
                                        or "VideoOut: vblank" in line],
        })
    return observations


def reference_symbols(root, wanted_nids):
    """Read registration/name evidence, retaining its exact source location."""
    root = Path(root)
    registrations = collections.defaultdict(list)
    names = collections.defaultdict(list)
    pattern = re.compile(r'LIB_FUNCTION\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*(\d+)\s*,\s*"([^"]+)"\s*,\s*([A-Za-z_]\w*(?:\([^()\n]*\))?)')
    for path in sorted((root / "src/core/libraries").rglob("*.cpp")):
        source = path.read_text(encoding="utf-8", errors="replace")
        for match in pattern.finditer(source):
            nid, library, version, module_name, implementation = match.groups()
            if nid in wanted_nids:
                registrations[f"{nid}#{library}"].append({
                    "library_version": int(version), "module": module_name, "module_version": None,
                    "implementation": implementation.strip(),
                    "source": str(path.relative_to(root)),
                    "line": source.count("\n", 0, match.start()) + 1,
                    "status": "reference registration only; native support unverified",
                })
    aero = root / "src/core/aerolib/aerolib.inl"
    if aero.is_file():
        for line_no, line in enumerate(aero.read_text(encoding="utf-8").splitlines(), 1):
            match = re.search(r'STUB\("([^"]+)",\s*([^)]*)\)', line)
            if match and match[1] in wanted_nids:
                names[match[1]].append({"name": match[2].strip(),
                                       "source": str(aero.relative_to(root)), "line": line_no})
    return registrations, names


def git_identity(root):
    result = {"path": str(Path(root).resolve()), "git_executable": shutil.which("git"),
              "status_options": ["-c", "core.autocrlf=true"]}
    for key, args in (("revision", ["rev-parse", "HEAD"]),
                      ("description", ["describe", "--tags", "--always", "--dirty"]),
                      ("status", ["status", "--short"])):
        proc = subprocess.run(["git", "-c", "core.autocrlf=true", "-C", str(root), *args],
                              capture_output=True, text=True, timeout=15)
        result[key] = proc.stdout.strip() if proc.returncode == 0 else None
    cmake = Path(root) / "CMakeLists.txt"
    if cmake.is_file():
        source = cmake.read_text(encoding="utf-8")
        result["version_components"] = dict(re.findall(r'set\(EMULATOR_VERSION_(MAJOR|MINOR|PATCH)\s+"([^"]+)"', source))
        result["version_is_wip"] = 'set(APP_VERSION "${APP_VERSION_NUM} WIP")' in source
    executables = []
    for directory, children, files in os.walk(root):
        children[:] = [child for child in children if child != ".git"]
        executables.extend(str((Path(directory) / name).relative_to(root))
                           for name in files if name.lower().endswith(".exe"))
    result["windows_executables"] = sorted(executables)
    return result


def windows_hardware():
    query = "$ErrorActionPreference='Stop'; @{cpu=@(Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors); gpu=@(Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,DriverDate); os=Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber,TotalVisibleMemorySize} | ConvertTo-Json -Depth 4 -Compress"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", query], capture_output=True, text=True, timeout=30)
    if result.returncode:
        return {"error": result.stderr.strip()}
    hardware = json.loads(result.stdout)
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        command = [nvidia_smi, "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"]
        query = subprocess.run(command, capture_output=True, text=True, timeout=15)
        hardware["nvidia_smi"] = {"command": command, "exit_code": query.returncode,
                                  "output": query.stdout.strip(), "error": query.stderr.strip()}
    return hardware


def collect(game, prepared, reference=None, record_paths=(), hardware=False):
    game, prepared = Path(game).resolve(), Path(prepared).resolve()
    analysis, link = read_json(prepared / "analysis.json"), read_json(prepared / "link.json")
    manifest = read_json(prepared / "prepared.json")
    names = prepared_imports(prepared / "boot-linked.bin")
    identities = collections.defaultdict(list)
    source_modules = []
    for filename in ("eboot.bin", *("sce_module/" + item["file"] for item in link["modules"])):
        data = module(game / filename)
        expected = manifest["inputs"].get(filename)
        if data["sha256"] != expected:
            raise ValueError(f"source module does not match prepared manifest: {filename}")
        source_modules.append({"file": filename, "sha256": data["sha256"], "matches_prepared_manifest": True})
        for symbol in data["symbols"]:
            identity = symbol.get("identity")
            if identity and symbol["section"] == 0:
                nid, library, module_name = identity
                item = {"source_module": filename, "encoded": symbol["name"], "symbol_type": symbol["type"],
                        "library": library[0], "library_version": library[1],
                        "module": module_name[0], "module_version": module_name[1]}
                if item not in identities[canonical(identity)]:
                    identities[canonical(identity)].append(item)
    observations = run_observations(record_paths)
    image_identity = file_identity(prepared / "boot-linked.bin")
    runtime_identities = {}
    for observation in observations:
        observation["matches_current_prepared_image"] = observation["image_sha256"] == image_identity["sha256"]
        runtime = observation["runtime"]
        if runtime:
            if runtime not in runtime_identities:
                runtime_identities[runtime] = file_identity(runtime)
            observation["runtime_identity_now"] = runtime_identities[runtime]
            observation["runtime_file_matches_recorded_hash"] = runtime_identities[runtime].get("sha256") == observation["runtime_sha256"]
    registrations, proven_names = reference_symbols(reference, {name.split("#")[0] for name in names}) if reference else ({}, {})
    unresolved = set(link["unresolved_imports"])
    inventory = []
    for index, name in enumerate(names):
        nid, _, library = name.partition("#")
        hints = []
        for identity in identities.get(name, []):
            hint = analysis.get("import_name_hints", {}).get(identity["encoded"])
            if hint and hint not in hints:
                hints.append(hint)
        inventory.append({"index": index, "canonical": name, "nid": nid, "library": library,
                          "identities": identities.get(name, []),
                          "calling_convention": "PS4 x86-64 System V ABI; data imports require their declared layout",
                          "name_hints_from_preparation": hints,
                          "reference_names": proven_names.get(nid, []),
                          "reference_registrations": registrations.get(name, []),
                          "prepared_link_status": "requires runtime resolution" if name in unresolved else "linked guest export",
                          "observed_missing_in": [o["record"]["path"] for o in observations if name in o["missing_imports"]],
                          "observed_fatal_calls_in": [o["record"]["path"] for o in observations
                                                      if {"canonical": name, "index": index} in o["fatal_imports"]]})
    layout = []
    for path in sorted(game.iterdir()):
        item = {"name": path.name, "type": "directory" if path.is_dir() else "file"}
        if path.is_file():
            item["bytes"] = path.stat().st_size
        else:
            item["immediate_children"] = [p.name for p in sorted(path.iterdir())]
        layout.append(item)
    return {"schema_version": 1, "collected_utc": datetime.now(timezone.utc).isoformat(),
            "collector": file_identity(__file__), "game": str(game),
            "metadata": analysis["sfo"], "content_layout": layout,
            "prepared_manifest": manifest, "source_modules": source_modules,
            "prepared_image": image_identity,
            "source_analysis": file_identity(prepared / "analysis.json"),
            "link_analysis": file_identity(prepared / "link.json"),
            "reference": git_identity(reference) if reference else None,
            "hardware": windows_hardware() if hardware else None,
            "run_observations": observations, "import_inventory": inventory,
            "import_summary": {"count": len(inventory), "libraries": dict(collections.Counter(i["library"] for i in inventory)),
                               "observed_missing": sum(bool(i["observed_missing_in"]) for i in inventory),
                               "observed_fatal": sum(bool(i["observed_fatal_calls_in"]) for i in inventory)},
            "evidence_limits": ["No runtime was launched by this collector.",
                                "Missing-import audits prove resolution status only for their recorded runtime/image hashes.",
                                "A fatal import call proves only that exact canonical symbol/table index was reached.",
                                "Static registrations and successful Vulkan initialization do not prove rendered frames, menu, gameplay, stability, or performance.",
                                "No frame/menu/gameplay/benchmark gate is promoted by this report."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", required=True, type=Path)
    parser.add_argument("--prepared", required=True, type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--run-record", type=Path, action="append", default=[])
    parser.add_argument("--hardware", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = collect(args.game, args.prepared, args.reference, args.run_record, args.hardware)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), **report["import_summary"]}, indent=2))


if __name__ == "__main__":
    main()
