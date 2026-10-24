"""Build the portable Linux package for the Go launcher.

The Linux package was removed with the Python launcher and is restored here for the Go one. It takes
the artifacts the native and Go builds already produce rather than building them itself:

  --runtime   out/order1886-runtime          (build.sh, ELF, rpath $ORIGIN/gpu)
  --gpu       out/gpu/libps4gpu.so           (the GPU library the runtime loads)
  --launcher  launcher-go/build/bin/The Order 1886   (wails build -platform linux/amd64)
  --worker    <pyinstaller onedir>/          (PyInstaller --onedir of launcher/order1886_worker.py)

Layout matches what the backend resolves: `bin/order1886-runtime`, the GPU library beside it in
`bin/gpu/`, and the worker in `bin/order1886-worker/`.

Nothing here has been run on Linux by the author of this file: it was written and reviewed on
Windows, so the workflow that calls it is the first real execution.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import time

# Libraries every Linux desktop with a Vulkan driver provides, and that must come from the system:
# the C/C++ runtime, the Vulkan loader and the graphics, display and audio stacks the drivers and
# SDL load. Everything else the runtime links is bundled, so the package does not depend on the
# build machine's FFmpeg, SDL3, fmt or Zydis versions. FFmpeg's VA-API and VDPAU loaders (libva,
# libvdpau) are bundled too: not every desktop installs them, and they still find the system's drivers.
SYSTEM_LIBRARY = re.compile(
    r'^(ld-linux.*|lib(c|m|dl|rt|pthread|util|resolv|anl|stdc\+\+|gcc_s|atomic)\.so.*'
    r'|libvulkan\.so.*|lib(GL|GLX|EGL|GLdispatch|OpenGL|gbm|drm)\b.*'
    r'|libX[A-Za-z0-9]*\.so.*|libxcb.*|libxkbcommon.*|libxshmfence.*|libwayland-.*|libdecor-.*|libasound\.so.*|libpulse.*|libjack.*'
    r'|libpipewire-.*|libdbus-1\.so.*|libsystemd\.so.*|libudev\.so.*|libz\.so.*|libexpat\.so.*'
    r'|libffi\.so.*|libbsd\.so.*|libmd\.so.*|libcap\.so.*)$')

SCRIPTS = (
    'prepare.py', 'link_modules.py', 'link_libc.py', 'save_backup.py',
    'order1886_frame_rate.py', 'order1886_display.py', 'order1886_post_effects.py', 'order1886_cache.py',
    'order1886_steam.py', 'order1886_mods.py', 'order1886_trophy_history.py', 'order1886_trophy_text.py',
    'order1886_input.py', 'order1886_frame_trace.py', 'order1886_perf_report.py',
    # order1886.py imports this by name from the shipped scripts/ directory.
    'order1886_patches.py',
)


def sha256(path: Path) -> str:
    return hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()


def fail(message: str) -> None:
    raise SystemExit(message)


def elf_or_fail(path: Path, what: str) -> None:
    with path.open('rb') as stream:
        if stream.read(4) != b'\x7fELF':
            fail(f'{what} is not an ELF binary: {path}')
    if not os.access(path, os.X_OK):
        fail(f'{what} is not executable: {path}')


def bundle_libraries(binaries: list[Path], target: Path) -> list[str]:
    """Copy the non-system shared-library closure of `binaries` into `target` (bin/gpu, already on
    the runtime's RUNPATH) and point every bundled library's RUNPATH at its own directory."""
    pending, seen, bundled = list(binaries), set(), []
    while pending:
        binary = pending.pop()
        result = subprocess.run(['ldd', str(binary)], capture_output=True, text=True, check=True)
        for line in result.stdout.splitlines():
            # "name => /some path/with spaces.so (0x...)" or "name => not found"
            match = re.match(r'\s*(\S+) => (.+?)(?: \(0x[0-9a-f]+\))?$', line)
            if not match:
                continue
            name, resolved = match.groups()
            if name in seen or SYSTEM_LIBRARY.match(name):
                continue
            seen.add(name)
            if resolved == 'not found':
                fail(f'{binary.name} needs {name}, which is not installed on the build machine')
            source = Path(resolved)
            if source.parent == target:
                continue  # libps4gpu.so itself
            shutil.copy2(source.resolve(), target / name)
            bundled.append(name)
            pending.append(target / name)
    for library in (*[target / name for name in bundled], target / 'libps4gpu.so'):
        subprocess.run(['patchelf', '--set-rpath', '$ORIGIN', str(library)], check=True)
    return sorted(bundled)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--gpu', type=Path, required=True)
    parser.add_argument('--launcher', type=Path, required=True)
    parser.add_argument('--worker', type=Path, required=True,
                        help='PyInstaller --onedir output directory')
    parser.add_argument('--output', type=Path, default=Path('out/order1886-go-package'))
    parser.add_argument('--skip-smoke', action='store_true')
    args = parser.parse_args()

    project = Path(__file__).resolve().parents[2]
    runtime = args.runtime.resolve()
    identity_path = runtime.parent / 'runtime-build.json'
    if not identity_path.is_file():
        fail('The runtime build receipt is missing next to the runtime; build it with build.sh first.')
    identity = json.loads(identity_path.read_text(encoding='utf-8'))
    digest = sha256(runtime)
    if identity.get('game_profile') != 'order1886' or identity.get('runtime_abi') != 'order1886-native-1':
        fail('This runtime is not a dedicated Order build.')
    if identity.get('runtime_sha256') not in (None, digest):
        fail('The runtime does not match its build receipt.')

    launcher = args.launcher.resolve()
    elf_or_fail(launcher, 'Go launcher')
    elf_or_fail(runtime, 'Runtime')
    gpu = args.gpu.resolve()
    elf_or_fail(gpu, 'GPU library')
    worker = args.worker.resolve()
    worker_binary = worker / 'order1886-worker'
    if not worker_binary.is_file():
        fail(f'PyInstaller worker binary is missing: {worker_binary}')

    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    stage = (project / args.output / stamp).resolve()
    destination = stage / 'The Order 1886'
    (destination / 'bin').mkdir(parents=True, exist_ok=True)
    (destination / 'notices').mkdir(parents=True, exist_ok=True)
    incomplete = destination / 'GO-BUILD-INCOMPLETE.txt'
    incomplete.write_text('This package is incomplete until packaging and smoke checks finish.\n',
                          encoding='utf-8')

    for name in ('The Order 1886', 'Play The Order 1886'):
        shutil.copy2(launcher, destination / name)
        (destination / name).chmod(0o755)
    shutil.copy2(runtime, destination / 'bin/order1886-runtime')
    (destination / 'bin/order1886-runtime').chmod(0o755)
    (destination / 'bin/gpu').mkdir()
    shutil.copy2(gpu, destination / 'bin/gpu/libps4gpu.so')
    # The runtime stays byte-identical to its receipt; its RUNPATH already starts with $ORIGIN/gpu.
    bundled = bundle_libraries([destination / 'bin/order1886-runtime', destination / 'bin/gpu/libps4gpu.so'],
                               destination / 'bin/gpu')
    print(f'Bundled {len(bundled)} libraries: {", ".join(bundled)}', flush=True)
    shutil.copy2(identity_path, destination / 'bin/runtime-build.json')
    shutil.copytree(worker, destination / 'bin/order1886-worker')
    for entry in (destination / 'bin/order1886-worker').iterdir():
        if entry.is_file() and entry.read_bytes()[:4] == b'\x7fELF':
            entry.chmod(0o755)

    script_dir = destination / 'scripts'
    script_dir.mkdir()
    for name in SCRIPTS:
        shutil.copy2(project / 'scripts' / name, script_dir / name)

    for name in ('LICENSE', 'README.md'):
        shutil.copy2(project / name, destination / name)
    # The frozen Python runtime, the PyInstaller bootloader and Pillow are redistributed with the
    # worker, so their licenses travel with it. The generator is platform-neutral; it reads the
    # build interpreter's metadata.
    notices_script = project / 'packaging/windows/order1886_notices.py'
    if notices_script.is_file():
        subprocess.run([sys.executable, str(notices_script), str(destination / 'notices/python')],
                       check=True)
    notices = project / 'packaging/windows'
    for source, target in (('ATTRIBUTION-Order1886.txt', 'notices/ATTRIBUTION.txt'),
                           ('README-Order1886.txt', 'README-Order1886.txt'),
                           ('QUICKSTART-Order1886.txt', 'QUICKSTART.txt')):
        if (notices / source).is_file():
            shutil.copy2(notices / source, destination / target)

    files = []
    for path in sorted(destination.rglob('*')):
        if path.is_file() and path.name != 'package-manifest.json':
            files.append({'path': str(path.relative_to(destination)), 'sha256': sha256(path)})
    manifest = {
        'product': 'The Order: 1886',
        'launcher': 'Go / Wails v2.17.0',
        'platform': 'linux-x86_64',
        'status': 'release',
        'built_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'runtime_sha256': digest,
        'runtime_build': identity,
        # The same recovery ABI the Windows package advertises: the helper is the same Go code.
        'update_abi': 'order1886-update-2',
        'source_revision': subprocess.run(['git', '-C', str(project), 'rev-parse', 'HEAD'],
                                          capture_output=True, text=True, check=False).stdout.strip(),
        'source_dirty': bool(subprocess.run(['git', '-C', str(project), 'status', '--porcelain'],
                                            capture_output=True, text=True, check=False).stdout.strip()),
        'files': files,
    }
    (destination / 'package-manifest.json').write_text(
        json.dumps(manifest, indent=2) + '\n', encoding='utf-8')

    if not args.skip_smoke:
        smoke = project / 'packaging/linux/order1886-go-smoke.py'
        result = subprocess.run([sys.executable, str(smoke), str(destination)], check=False)
        if result.returncode:
            fail('Linux portable smoke failed; the incomplete marker remains.')
    incomplete.unlink()

    archive = stage / 'order1886-linux-x86_64.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        tar.add(destination, arcname='The Order 1886')
    (stage / 'order1886-linux-x86_64.tar.gz.sha256').write_text(
        f'{sha256(archive)}  {archive.name}\n', encoding='utf-8')
    print(archive)


if __name__ == '__main__':
    main()
