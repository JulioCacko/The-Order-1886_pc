#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Check, and repair, the shared libraries a Linux package of the runtime depends on (#5).

The 0.2.17 package shipped `bin/gpu/libps4gpu.so` with RUNPATH `/tmp/ffmstage/usr/lib64`, a
folder on the machine that built it. The dynamic linker therefore never looked in `bin/gpu/`
for that library's dependencies, and every system without Zydis 5 failed at start with
"error while loading shared libraries: libZydis.so.5", although the file was right there.
The same package also took FFmpeg (libavcodec.so.63 and friends) and libfmt.so.12 from the
system instead of bundling them, which only works where the distribution ships exactly
those versions.

  check <package>   Read the ELF files (nothing is executed) and list every dependency that
                    would come from outside the package although it is not a base-system
                    library, and every RUNPATH that points outside the package. Exit 1 on
                    any problem. Run it before publishing a release.
  fix <package>     Copy those dependencies, and their own dependencies, from this machine
                    into bin/gpu/, point the RUNPATH of libps4gpu.so and of every bundled
                    library at $ORIGIN (patchelf), then check again.

The base-system list is the one the upstream packager uses
(packaging/linux/order1886-go-package.py, SYSTEM_LIBRARY): the C/C++ runtime, the Vulkan
loader, and the graphics, display and audio stacks the drivers and SDL load. Everything else
is bundled.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

SYSTEM_LIBRARY = re.compile(
    r'^(ld-linux.*|lib(c|m|mvec|dl|rt|pthread|util|resolv|anl|stdc\+\+|gcc_s|atomic)\.so.*'
    r'|libvulkan\.so.*|lib(GL|GLX|EGL|GLdispatch|OpenGL|gbm|drm)\b.*'
    r'|libX[A-Za-z0-9]*\.so.*|libxcb.*|libxkbcommon.*|libxshmfence.*|libwayland-.*|libdecor-.*|libasound\.so.*|libpulse.*|libjack.*'
    r'|libpipewire-.*|libdbus-1\.so.*|libsystemd\.so.*|libudev\.so.*|libz\.so.*|libexpat\.so.*'
    r'|libffi\.so.*|libbsd\.so.*|libmd\.so.*|libcap\.so.*)$')

PT_LOAD, PT_DYNAMIC = 1, 2
DT_NULL, DT_NEEDED, DT_STRTAB, DT_RPATH, DT_RUNPATH = 0, 1, 5, 15, 29


def dynamic_info(path: Path) -> tuple[list[str], list[str]]:
    """(DT_NEEDED names, RUNPATH or RPATH entries) of a 64-bit little-endian ELF."""
    data = path.read_bytes()
    if data[:4] != b'\x7fELF' or data[4] != 2 or data[5] != 1:
        raise ValueError(f'{path}: not a 64-bit little-endian ELF')
    phoff, = struct.unpack_from('<Q', data, 0x20)
    phentsize, phnum = struct.unpack_from('<HH', data, 0x36)
    loads, dynamic = [], None
    for index in range(phnum):
        p_type, _, p_offset, p_vaddr, _, p_filesz, _, _ = struct.unpack_from(
            '<IIQQQQQQ', data, phoff + index * phentsize)
        if p_type == PT_LOAD:
            loads.append((p_vaddr, p_offset, p_filesz))
        elif p_type == PT_DYNAMIC:
            dynamic = (p_offset, p_filesz)
    if dynamic is None:
        return [], []

    def file_offset(vaddr: int) -> int:
        for start, offset, size in loads:
            if start <= vaddr < start + size:
                return offset + vaddr - start
        raise ValueError(f'{path}: address {vaddr:#x} is not in a loaded segment')

    entries, strtab = [], None
    for position in range(dynamic[0], dynamic[0] + dynamic[1], 16):
        tag, value = struct.unpack_from('<qQ', data, position)
        if tag == DT_NULL:
            break
        if tag == DT_STRTAB:
            strtab = file_offset(value)
        entries.append((tag, value))

    def string(offset: int) -> str:
        end = data.index(b'\0', strtab + offset)
        return data[strtab + offset:end].decode('utf-8', 'replace')

    needed = [string(value) for tag, value in entries if tag == DT_NEEDED]
    runpath = [string(value) for tag, value in entries if tag == DT_RUNPATH]
    if not runpath:  # DT_RPATH only counts when there is no DT_RUNPATH
        runpath = [string(value) for tag, value in entries if tag == DT_RPATH]
    return needed, [entry for item in runpath for entry in item.split(':') if entry]


def audit(package: Path, warnings: list[str] | None = None) -> list[str]:
    """Problems in the closure of bin/order1886-runtime.bin and every library in bin/gpu/.

    Resolution follows the dynamic linker for these objects: a dependency is looked up in the
    RUNPATH of the object that needs it, with $ORIGIN expanded; a library another object of the
    package already loaded by that soname is reused (which is how a bundled copy can serve an
    object without the right RUNPATH, and why such an object still counts as a problem)."""
    bindir = (package / 'bin').resolve()
    runtime = bindir / 'order1886-runtime.bin'
    if not runtime.is_file():
        raise SystemExit(f'{runtime} is missing: point this at an unpacked package folder')
    warnings = [] if warnings is None else warnings
    problems, seen, pending = [], set(), [runtime]
    while pending:
        obj = pending.pop()
        if obj in seen:
            continue
        seen.add(obj)
        needed, runpath = dynamic_info(obj)
        relative = obj.relative_to(package.resolve())
        for index, entry in enumerate(runpath):
            if not entry.startswith('$ORIGIN'):
                if any(e.startswith('$ORIGIN') for e in runpath[:index]):
                    # Searched only after the package: the upstream packager keeps the runtime
                    # byte-identical to its build receipt with this build-tree entry in it.
                    warnings.append(f'{relative}: RUNPATH entry {entry} (after $ORIGIN) is a build path')
                else:
                    problems.append(f'{relative}: RUNPATH entry {entry} points outside the package')
        dirs = [Path(entry.replace('$ORIGIN', str(obj.parent))) for entry in runpath
                if entry.startswith('$ORIGIN')]
        for name in needed:
            if SYSTEM_LIBRARY.match(name):
                continue
            found = next((d / name for d in dirs if (d / name).is_file()), None)
            if found is None:
                where = 'bundled in bin/gpu/ but not on its RUNPATH' if (bindir / 'gpu' / name).is_file() \
                    else 'not bundled: it would come from the system'
                problems.append(f'{relative} needs {name}: {where}')
                continue
            pending.append(found.resolve())
    return problems


def ldd_closure(binary: Path) -> dict[str, Path]:
    """name -> host path of every non-system dependency, resolved by this machine's linker."""
    result = subprocess.run(['ldd', str(binary)], capture_output=True, text=True, check=True,
                            env={'LC_ALL': 'C', 'PATH': '/usr/bin:/bin'})
    found = {}
    for line in result.stdout.splitlines():
        match = re.match(r'\s*(\S+) => (.+?)(?: \(0x[0-9a-f]+\))?$', line)
        # The loader is listed by absolute path (/lib64/ld-linux-x86-64.so.2 => ...).
        if not match or '/' in match.group(1) or SYSTEM_LIBRARY.match(match.group(1)):
            continue
        name, resolved = match.groups()
        if resolved == 'not found':
            raise SystemExit(f'{binary.name} needs {name}, which this machine does not have either')
        found[name] = Path(resolved)
    return found


def host_library(name: str) -> Path | None:
    """This machine's x86-64 copy of a soname, from the linker cache; None if it has none."""
    result = subprocess.run(['ldconfig', '-p'], capture_output=True, text=True, check=True,
                            env={'LC_ALL': 'C', 'PATH': '/usr/sbin:/sbin:/usr/bin:/bin'})
    for line in result.stdout.splitlines():
        match = re.match(r'\s*(\S+) \(([^)]*)\) => (\S+)$', line)
        if match and match.group(1) == name and 'x86-64' in match.group(2):
            return Path(match.group(3)).resolve()
    return None


def same_library(bundled: Path, host: Path, patchelf: str) -> bool:
    """True when bundled is host's file plus at most a RUNPATH of $ORIGIN."""
    if bundled.read_bytes() == host.read_bytes():
        return True
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        copy = Path(folder) / host.name
        shutil.copy2(host, copy)
        copy.chmod(0o755)
        subprocess.run([patchelf, '--set-rpath', '$ORIGIN', str(copy)], check=True)
        return copy.read_bytes() == bundled.read_bytes()


def fix(package: Path, patchelf: str) -> list[str]:
    """Bundle the closure into bin/gpu/ with RUNPATH $ORIGIN everywhere.

    Where this machine has a library, its copy is the one bundled, replacing a stale one: the
    0.2.17 bin/gpu/ still held FFmpeg 6's libva.so.2, which the new libavutil.so.61 cannot use
    (undefined symbol vaMapBuffer2). A copy already in the package is kept only when this
    machine has no such library (Zydis 5 on most distributions). Each library gets its RUNPATH
    before its own dependencies are resolved, so ldd sees the package as the runtime will."""
    gpu = (package / 'bin/gpu').resolve()
    runtime = (package / 'bin/order1886-runtime.bin').resolve()

    def set_origin(library: Path) -> None:
        if library.parent != gpu:
            raise SystemExit(f'refusing to modify {library}: it is outside {gpu}')
        subprocess.run([patchelf, '--set-rpath', '$ORIGIN', str(library)], check=True)

    changed, seen = [], set()
    set_origin(gpu / 'libps4gpu.so')
    pending = [runtime, gpu / 'libps4gpu.so']
    while pending:
        binary = pending.pop()
        for name, _ in ldd_closure(binary).items():
            if name in seen:
                continue
            seen.add(name)
            target = gpu / name
            host = host_library(name)
            if host is not None:
                # A bundled copy differs from the host's only by the RUNPATH set below; compare
                # with that cleared, so a package fixed before is not reported as replaced.
                if not target.is_file() or not same_library(target, host, patchelf):
                    action = 'replaced' if target.is_file() else 'added'
                    target.unlink(missing_ok=True)
                    shutil.copy2(host, target)
                    target.chmod(0o755)
                    changed.append(f'{name} ({action})')
            elif not target.is_file():
                raise SystemExit(f'{name} is neither in the package nor on this machine')
            set_origin(target)
            pending.append(target)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('mode', choices=('check', 'fix'))
    parser.add_argument('package', type=Path, help='the unpacked "The Order 1886" folder')
    parser.add_argument('--patchelf', default='patchelf', help='patchelf executable (fix only)')
    args = parser.parse_args()
    if args.mode == 'fix':
        if shutil.which(args.patchelf) is None:
            raise SystemExit(f'{args.patchelf} not found: install patchelf or pass --patchelf')
        bundled = fix(args.package, args.patchelf)
        print(f'{len(bundled)} libraries added or replaced: {", ".join(bundled) or "none"}')
    warnings: list[str] = []
    problems = audit(args.package, warnings)
    for warning in warnings:
        print('warning:', warning)
    for problem in problems:
        print(problem)
    print('OK: every non-system dependency resolves inside the package.' if not problems
          else f'{len(problems)} problem(s).')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
