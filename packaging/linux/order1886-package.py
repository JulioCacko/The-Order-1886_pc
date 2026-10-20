#!/usr/bin/env python3
"""Build a Linux x86-64 launcher bundle from an already verified native build."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ('prepare', 'link_modules', 'link_libc', 'save_backup', 'order1886_frame_rate',
           'order1886_display', 'order1886_cache', 'order1886_steam', 'order1886_mods', 'order1886_input',
           # order1886.py imports the patch catalogue by name from scripts/; a missing entry is a
           # ModuleNotFoundError on Play, not a degraded feature.
           'order1886_patches')
SYSTEM_LIBS = re.compile(r'^(?:ld-linux|lib(?:c|m|pthread|dl|rt|resolv|util)\.so|libnss_)')


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def dependencies(output):
    if 'not found' in output:
        raise ValueError('Unresolved native dependency:\n' + output)
    result = {}
    for line in output.splitlines():
        match = re.match(r'\s*(\S+)\s+=>\s+(/\S+)\s+\(', line)
        if match and not SYSTEM_LIBS.match(match[1]):
            path = Path(match[2])
            if not match[2].startswith('/usr/lib/wsl/'):
                result[match[1]] = path
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/order1886-linux')
    args = parser.parse_args()
    if sys.platform != 'linux' or platform.machine() != 'x86_64':
        parser.error('Build this package on Linux x86-64')
    runtime = ROOT / 'out/order1886-runtime'
    renderer = ROOT / 'out/gpu/libps4gpu.so'
    receipt = json.loads(runtime.with_name('runtime-build.json').read_text())
    if receipt.get('runtime_sha256') != sha256(runtime) or receipt.get('game_profile') != 'order1886':
        raise ValueError('Native runtime does not match its build identity')
    build_id = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + sha256(runtime)[:12]
    stage = args.output.resolve() / build_id
    stage.mkdir(parents=True, exist_ok=False)
    package = stage / 'The Order 1886'
    data = stage / 'scripts'
    data.mkdir()
    for name in SCRIPTS:
        shutil.copy2(ROOT / f'scripts/{name}.py', data)
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
               '--name', 'order1886-launcher', '--distpath', str(stage / 'frozen'),
               '--workpath', str(stage / 'work'), '--specpath', str(stage),
               '--paths', str(ROOT), '--paths', str(ROOT / 'launcher'),
               '--paths', str(ROOT / 'scripts'),
               '--add-data', f'{data}:scripts',
               '--add-data', f'{ROOT / "launcher/order1886"}:launcher/order1886']
    for name in ('order1886', 'order1886_lang', 'order1886_lang_data',
                 'PIL._tkinter_finder', 'PIL._imagingtk', *SCRIPTS):
        command.extend(('--hidden-import', name))
    command.append(str(ROOT / 'launcher/order1886_launcher.py'))
    subprocess.run(command, cwd=ROOT, check=True)
    shutil.copytree(stage / 'frozen/order1886-launcher', package)
    (package / 'bin/gpu').mkdir(parents=True)
    (package / 'bin/lib').mkdir()
    shutil.copy2(runtime, package / 'bin/order1886-runtime')
    shutil.copy2(renderer, package / 'bin/gpu/libps4gpu.so')
    receipt['renderer_sha256'] = sha256(renderer)
    (package / 'bin/runtime-build.json').write_text(json.dumps(receipt, indent=2) + '\n')

    libraries = {}
    for binary in (runtime, renderer):
        libraries.update(dependencies(subprocess.check_output(['ldd', str(binary)], text=True)))
    licenses = package / 'licenses'
    licenses.mkdir()
    for name, path in sorted(libraries.items()):
        if name == 'libps4gpu.so':
            continue
        shutil.copy2(path, package / 'bin/lib' / name)
        owned = subprocess.check_output(['dpkg-query', '-S', str(path.resolve())], text=True)
        owner = owned.split(': /', 1)[0].split(':', 1)[0]
        copyright_file = Path('/usr/share/doc') / owner / 'copyright'
        shutil.copy2(copyright_file, licenses / (owner + '-copyright.txt'))
    for name in ('LICENSE', 'packaging/windows/ATTRIBUTION-Order1886.txt'):
        shutil.copy2(ROOT / name, licenses / Path(name).name)
    for distribution in ('PyInstaller', 'Pillow'):
        import importlib.metadata
        info = importlib.metadata.distribution(distribution)
        for file in info.files or ():
            if any(part.lower() in ('licenses', 'license', 'copying') or part.lower().startswith('license.') for part in file.parts):
                source = Path(info.locate_file(file))
                if source.is_file():
                    target = licenses / distribution / file
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)

    launcher = package / 'The Order 1886'
    launcher.write_text('#!/bin/sh\nbase=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1\n'
        'export LD_LIBRARY_PATH="$base/bin/gpu:$base/bin/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"\n'
        'exec "$base/order1886-launcher" "$@"\n')
    direct = package / 'Play The Order 1886'
    direct.write_text('#!/bin/sh\nbase=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1\n'
                      'exec "$base/The Order 1886" --play "$@"\n')
    launcher.chmod(0o755)
    direct.chmod(0o755)
    shutil.copy2(ROOT / 'packaging/linux/README.md', package / 'QUICKSTART-Linux.txt')
    manifest = {'platform': 'linux-x86_64', 'package_version': '0.1.3', 'build_id': build_id,
                'runtime_build': receipt, 'glibc': platform.libc_ver()[1],
                'files': {str(p.relative_to(package)): sha256(p)
                          for p in sorted(package.rglob('*')) if p.is_file()}}
    (package / 'package-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    archive = stage / 'order1886-linux-x86_64.tar.gz'
    with tarfile.open(archive, 'w:gz') as output:
        output.add(package, arcname=package.name,
                   filter=lambda entry: entry.replace(uid=0, gid=0, uname='root', gname='root', deep=False))
    archive.with_name(archive.name + '.sha256').write_text(sha256(archive) + '  ' + archive.name + '\n')
    print(json.dumps({'package': str(package), 'archive': str(archive), 'sha256': sha256(archive)}, indent=2))


if __name__ == '__main__':
    main()
