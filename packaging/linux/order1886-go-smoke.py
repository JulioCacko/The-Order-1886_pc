"""Relocated Linux package smoke. No game process and no player state is touched.

Checks what a relocated copy must still satisfy: the manifest and every hash, ELF entry points that
run, the worker answering the protocol the launcher uses, and a clean update helper. It never starts
The Order: 1886 and never claims gameplay.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile


def elfish(path: Path) -> bool:
    with path.open('rb') as stream:
        return stream.read(4) == b'\x7fELF'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    args = parser.parse_args()
    package = args.package.resolve()

    manifest_path = package / 'package-manifest.json'
    if not manifest_path.is_file():
        raise SystemExit('The package manifest is missing.')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('update_abi') != 'order1886-update-2':
        raise SystemExit('Package does not advertise the update recovery ABI.')
    if manifest.get('platform') != 'linux-x86_64':
        raise SystemExit('Package does not declare the Linux platform.')
    if (manifest.get('runtime_build') or {}).get('runtime_abi') != 'order1886-native-1':
        raise SystemExit('Package runtime is not a dedicated Order build.')

    for entry in manifest['files']:
        path = package / entry['path']
        if not path.resolve().is_relative_to(package):
            raise SystemExit('Manifest path escapes the package: ' + entry['path'])
        if hashlib.file_digest(path.open('rb'), 'sha256').hexdigest() != entry['sha256']:
            raise SystemExit('Package hash mismatch: ' + entry['path'])

    for relative in ('The Order 1886', 'Play The Order 1886', 'bin/order1886-launcher',
                     'bin/order1886-runtime', 'bin/gpu/libps4gpu.so'):
        path = package / relative
        if not path.is_file():
            raise SystemExit('Missing packaged file: ' + relative)
        if not elfish(path):
            raise SystemExit('Not an ELF binary: ' + relative)
    if not os.access(package / 'The Order 1886', os.X_OK):
        raise SystemExit('The launcher is not executable in the package.')
    # Both entry points must start where WebKitGTK is missing (SteamOS, #114); only the window links it.
    for relative in ('The Order 1886', 'Play The Order 1886'):
        dynamic = subprocess.run(['readelf', '-d', str(package / relative)], capture_output=True,
                                 text=True, check=True).stdout
        linked = [name for name in re.findall(r'Shared library: \[([^\]]+)\]', dynamic)
                  if re.search(r'webkit|javascriptcore|gtk|gdk|soup', name)]
        if linked:
            raise SystemExit(f'{relative} links the launcher window libraries: {", ".join(linked)}')

    # Every library the packager bundled must be the one the runtime loads, so a machine without the
    # build host's FFmpeg, SDL3, fmt or Zydis still starts it.
    gpu = package / 'bin/gpu'
    bundled = {path.name for path in gpu.iterdir()} - {'libps4gpu.so'}
    if not bundled:
        raise SystemExit('No libraries were bundled beside the GPU library.')
    for binary in (package / 'bin/order1886-runtime', gpu / 'libps4gpu.so'):
        # Their own dependencies must come from the package. A library the system stack loads first
        # (libnuma through a system driver, say) may resolve outside it, which is harmless.
        dynamic = subprocess.run(['readelf', '-d', str(binary)], capture_output=True, text=True,
                                 check=True).stdout
        needed = set(re.findall(r'Shared library: \[([^\]]+)\]', dynamic))
        # As a player starts it: no LD_LIBRARY_PATH (the build job points it at /usr/local/lib).
        plain = {key: value for key, value in os.environ.items() if key != 'LD_LIBRARY_PATH'}
        listing = subprocess.run(['ldd', str(binary)], capture_output=True, text=True, check=True,
                                 env=plain).stdout
        for line in listing.splitlines():
            name, _, resolved = line.strip().partition(' => ')
            if 'not found' in resolved:
                raise SystemExit(f'{binary.name}: {name} is not found')
            path = re.sub(r' \(0x[0-9a-f]+\)$', '', resolved)  # paths here contain spaces
            if name in needed & bundled and not Path(path).resolve().is_relative_to(gpu):
                raise SystemExit(f'{binary.name} loads {name} from outside the package: {resolved}')

    with tempfile.TemporaryDirectory(prefix='Order Go smoke ') as temporary:
        root = Path(temporary) / 'Portable ç 日本語'
        shutil.copytree(package, root, symlinks=True)
        state = Path(temporary) / 'isolated player'
        environment = dict(os.environ, PATH='/usr/bin:/bin', PYTHONPATH='')

        for name in ('The Order 1886', 'Play The Order 1886'):
            result = subprocess.run([str(root / name), '--worker-smoke', '--state-dir', str(state)],
                                    cwd=temporary, env=environment, timeout=60, capture_output=True)
            if result.returncode:
                raise SystemExit(f'{name} failed its worker smoke: '
                                 + result.stderr.decode('utf-8', 'replace')[-600:])

        # A system without WebKitGTK: the window fails in the dynamic linker. The entry must say so
        # and, with no game folder saved, explain --game-dir instead of failing silently.
        window = root / 'bin/order1886-launcher'
        window.rename(window.with_name('order1886-launcher.real'))
        window.write_text('#!/bin/sh\necho "$0: error while loading shared libraries: '
                          'libwebkit2gtk-4.1.so.0: cannot open shared object file: No such file or '
                          'directory" >&2\nexit 127\n', encoding='utf-8')
        window.chmod(0o755)
        headless = {key: value for key, value in environment.items() if key not in ('DISPLAY', 'WAYLAND_DISPLAY')}
        result = subprocess.run([str(root / 'The Order 1886'), '--state-dir', str(state)], cwd=temporary,
                                env=headless, timeout=120, capture_output=True)
        message = result.stderr.decode('utf-8', 'replace')
        if (result.returncode == 0 or 'needs WebKitGTK 4.1' not in message
                or 'libwebkit2gtk-4.1.so.0' not in message or '--game-dir' not in message):
            raise SystemExit('Missing WebKitGTK was not reported: ' + message[-800:])
        if 'needs WebKitGTK 4.1' not in (state / 'logs/launcher-entry.log').read_text(encoding='utf-8'):
            raise SystemExit('Missing WebKitGTK was not logged for players without a terminal.')
        window.unlink()
        window.with_name('order1886-launcher.real').rename(window)

        recovery = subprocess.run([str(root / 'The Order 1886'), '--update-helper',
                                   '--update-action', 'recover', '--update-installation', str(root),
                                   '--no-relaunch'],
                                  cwd=temporary, env=environment, timeout=60, capture_output=True)
        if recovery.returncode:
            raise SystemExit('Update helper refused a clean package: '
                             + recovery.stderr.decode('utf-8', 'replace')[-600:])
        if (root / '.order1886-update' / 'journal.json').exists():
            raise SystemExit('Update helper wrote a journal for a clean package.')

        worker = root / 'bin/order1886-worker/order1886-worker'
        if not worker.is_file():
            raise SystemExit('The packaged worker binary is missing.')
        backend = subprocess.run([str(worker), '--run-backend', '--help'],
                                 cwd=temporary, env=environment, timeout=120, capture_output=True)
        if backend.returncode != 0:
            raise SystemExit('Packaged backend cannot import its modules: '
                             + (backend.stderr or backend.stdout).decode('utf-8', 'replace')[-600:])

        requests = [
            dict(version=1, id=1, method='settings.set', params={'values': {'vsync': False, 'ui_language': 'pt'}}),
            dict(version=1, id=2, method='settings.set', params={'values': {'frame_rate': 120}}),  # 30, 60, 90 and 0 are offered
            dict(version=1, id=3, method='state.get', params={}),
            dict(version=1, id=4, method='updates.preflight', params={}),
            dict(version=1, id=5, method='patches.list', params={}),
        ]
        result = subprocess.run([str(worker), '--state-dir', str(state),
                                 '--installation-root', str(root)],
                                input=''.join(json.dumps(r) + '\n' for r in requests),
                                text=True, encoding='utf-8', capture_output=True,
                                timeout=60, cwd=temporary, env=environment)
        if result.returncode:
            raise SystemExit('Worker protocol run failed: ' + result.stderr[-600:])
        replies = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        if len(replies) != len(requests):
            raise SystemExit(f'Worker answered {len(replies)} of {len(requests)} requests.')
        if replies[0]['result']['settings']['vsync'] is not False:
            raise SystemExit('Worker did not store a valid setting.')
        if 'error' not in replies[1]:
            raise SystemExit('Worker accepted a frame rate it should reject as a patch.')
        state_snapshot = replies[2]['result']
        if state_snapshot['settings']['ui_language'] != 'pt':
            raise SystemExit('Worker lost the stored language.')
        if len(state_snapshot['pages']) != 7 or len(state_snapshot['languages']) != 13:
            raise SystemExit('Worker surfaced the wrong page or language count.')
        if replies[3]['result']['ready'] is not True:
            raise SystemExit('Update preflight is not ready on a clean package.')
        rows = replies[4]['result']['recipes']
        if len(rows) < 2 or not all(row['id'] and row['title'] for row in rows):
            raise SystemExit('Patch catalogue is empty or unlabelled.')
        if not all(row['applicable'] is False and row['reason'] for row in rows):
            raise SystemExit('A recipe claims applicability without a selected game.')
        if (state / 'savedata').exists():
            raise SystemExit('The smoke created save data.')

    print('Linux portable smoke passed: manifest and hashes, ELF entry points without WebKitGTK, '
          'missing-WebKitGTK report, update ABI and clean helper, Unicode relocation, restricted PATH, '
          'worker protocol, update preflight, autosave, language and rejected settings.')


if __name__ == '__main__':
    main()
