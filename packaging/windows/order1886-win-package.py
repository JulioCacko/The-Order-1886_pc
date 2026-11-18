"""Finalize the Windows package from the CI-built tree.

The native build and the portable assembly happen in the source repository's
`order1886-go-package.yml` (windows-2025 + MSYS2 CLANG64 + `packaging/windows/order1886-go-build.ps1`);
its artifact is a staged folder named exactly `The Order 1886` with its own
`package-manifest.json`. This script is the release repository's gate before upload:

  1. verify every manifest entry hashes correctly and every shipped file is listed
     (the same discipline as packaging/linux/order1886-go-package.py);
  2. re-write the manifest with sorted paths so the shipped bytes are stable;
  3. produce `order1886-win-x86_64-<version>.zip` (root folder `The Order 1886/`) and
     its `.sha256` in the GNU two-space format.

Windows content rules checked here, because the Linux builder cannot see them:
  - bin/order1886-runtime.exe and the two entry .exe launchers exist;
  - the upscaler providers (order1886_fsr3.dll, order1886_fsr4.dll) are present;
  - if bin/fsr4/ is present it carries LICENSE-FSR4-v07.txt (MIT bundle);
  - no .so files, no sh wrappers, no /proc-dependent helpers slipped in;
  - user/ is absent (settings and saves are created next to the launcher on first run).

Usage:
    python3 packaging/windows/order1886-win-package.py --tree "/path/The Order 1886" \
        --version v0.2.18 --out dist/ [--extra release-docs/]

--extra merges release-repository documents (CHANGES.md, WINDOWS.md, docs/verification/…)
into the package before the manifest is rebuilt — the parity step that makes the Windows
zip carry the same reading material the Linux tarball ships. Any manifest drift from the
merge is resolved by regenerating the file list from disk.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT_FOLDER = 'The Order 1886'
REQUIRED = ['bin/order1886-runtime.exe',
            'Play The Order 1886.exe',
            'The Order 1886.exe',
            'bin/order1886_fsr3.dll',
            'bin/order1886_fsr4.dll',
            'LICENSE', 'QUICKSTART.txt', 'README-Order1886.txt', 'package-manifest.json']
FORBIDDEN_SUFFIXES = ('.so', '.sh')


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, required=True,
                        help='staged folder (…/The Order 1886) from the CI artifact')
    parser.add_argument('--version', default='', help='zip name stamp, e.g. v0.2.18')
    parser.add_argument('--extra', type=Path, default=None,
                        help='release-repo docs folder merged in before the manifest is rebuilt')
    parser.add_argument('--out', type=Path, default=Path('.'), help='where to write zip + .sha256')
    args = parser.parse_args()

    tree = args.tree.resolve()
    if tree.name != ROOT_FOLDER or not tree.is_dir():
        raise SystemExit(f'--tree must be a folder named {ROOT_FOLDER!r}: {tree}')

    problems = []
    for relative in REQUIRED:
        if not (tree / relative).is_file():
            problems.append(f'missing required file: {relative}')
    manifest_path = tree / 'package-manifest.json'
    if not manifest_path.is_file():
        raise SystemExit('the CI artifact has no package-manifest.json; run the package workflow first')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))

    if args.extra:
        import shutil
        src = args.extra.resolve()
        merged = 0
        for path in sorted(src.rglob('*')):
            if path.is_file():
                target = tree / path.relative_to(src)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                merged += 1
        manifest['files'] = [{'path': p.relative_to(tree).as_posix(), 'sha256': sha256(p)}
                             for p in sorted(tree.rglob('*'))
                             if p.is_file() and p.name != 'package-manifest.json']
        print(f'merged {merged} release docs; manifest rebuilt over {len(manifest["files"])} files')

    listed = {entry['path'] for entry in manifest['files']}
    on_disk = []
    for path in sorted(tree.rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(tree).as_posix()
        if relative == 'package-manifest.json':
            continue
        on_disk.append(relative)
        if path.suffix in FORBIDDEN_SUFFIXES:
            problems.append(f'Linux-only artifact shipped: {relative}')
        if relative not in listed:
            problems.append(f'not listed in the manifest: {relative}')
    for entry in manifest['files']:
        path = tree / entry['path']
        if not path.is_file():
            problems.append(f'manifest entry missing on disk: {entry["path"]}')
        elif sha256(path) != entry['sha256']:
            problems.append(f'hash mismatch: {entry["path"]}')
    fsr4 = tree / 'bin' / 'fsr4'
    if fsr4.is_dir() and not (fsr4 / 'LICENSE-FSR4-v07.txt').is_file():
        problems.append('bin/fsr4/ present without LICENSE-FSR4-v07.txt')
    if (tree / 'user').exists():
        problems.append('user/ must not ship (settings and saves live beside the launcher at runtime)')
    missing_from_disk = listed.difference(on_disk)
    for relative in sorted(missing_from_disk):
        problems.append(f'manifest lists a file that is gone: {relative}')

    if problems:
        for problem in problems:
            print('PACKAGE PROBLEM:', problem, file=sys.stderr)
        return 1

    manifest['files'] = sorted(manifest['files'], key=lambda entry: entry['path'])
    # Same schema as the Linux release manifest, which declares its platform.
    manifest['platform'] = 'windows-x86_64'
    manifest_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')

    suffix = f'-{args.version}' if args.version else ''
    args.out.mkdir(parents=True, exist_ok=True)
    zip_path = args.out / f'order1886-win-x86_64{suffix}.zip'
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(tree.rglob('*')):
            if path.is_file():
                archive.write(path, f'{ROOT_FOLDER}/{path.relative_to(tree).as_posix()}')
    digest = sha256(zip_path)
    zip_path.with_suffix(zip_path.suffix + '.sha256').write_text(f'{digest}  {zip_path.name}\n', encoding='ascii')
    print(f'files: {len(on_disk) + 1}, zip: {zip_path}, sha256: {digest}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
