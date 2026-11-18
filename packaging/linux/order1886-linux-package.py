#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Finalize the Linux package from the CI-built tree.

The native build and the portable assembly happen in the source repository's
`order1886-go-linux-package.yml` (ubuntu-24.04, glibc 2.39, upstream's
`packaging/linux/order1886-go-package.py`, which bundles the non-system library closure into
`bin/gpu/` with RUNPATH `$ORIGIN`). Its artifact is `order1886-linux-x86_64.tar.gz` with the
top folder `The Order 1886/` and its own `package-manifest.json`. This script is the release
repository's gate before upload, the Linux twin of `packaging/windows/order1886-win-package.py`:

  1. merge what the CI tree does not carry: the platform-neutral FSR 4 v07 bundle
     (`--fsr4`, from the previous package), the release documents (`--extra`: CHANGES.md,
     README.md, docs/verification/...), and optionally `music/` (`--music`);
  2. run `order1886-bundle.py check` on the result (every non-system library must resolve
     inside the package, #5);
  3. verify every manifest entry still hashes correctly, rebuild the file list over the
     merged tree with sorted paths, keep the CI's build metadata, stamp the version;
  4. write `order1886-linux-x86_64-<version>.tar.gz` (root folder `The Order 1886/`) and its
     `.sha256` in the GNU two-space format.

Usage:
    python3 packaging/linux/order1886-linux-package.py --tree "/path/The Order 1886" \
        --version v0.2.22 --fsr4 "<previous package>/The Order 1886/bin/fsr4" \
        --extra release-docs/ [--music "<previous package>/The Order 1886/music"] --out dist/
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
import tarfile
import time
from pathlib import Path

ROOT_FOLDER = 'The Order 1886'
REQUIRED = ['bin/order1886-runtime', 'bin/order1886-runtime.bin', 'bin/gpu/libps4gpu.so', 'bin/order1886-worker/order1886-worker',
            'bin/order1886_fsr3.so', 'bin/order1886_fsr4.so', 'bin/runtime-build.json',
            'The Order 1886', 'Play The Order 1886',
            'LICENSE', 'QUICKSTART.txt', 'README-Order1886.txt', 'package-manifest.json']
FORBIDDEN_SUFFIXES = ('.exe', '.dll')


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def copy_tree(source: Path, target: Path) -> int:
    copied = 0
    for path in sorted(source.rglob('*')):
        if path.is_file():
            destination = target / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            copied += 1
    return copied


def bundle_check(tree: Path) -> list[str]:
    """order1886-bundle.py's check, in process; its problems as strings."""
    script = Path(__file__).with_name('order1886-bundle.py')
    spec = importlib.util.spec_from_file_location('order1886_bundle', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    warnings: list[str] = []
    problems = module.audit(tree, warnings)
    for warning in warnings:
        print('bundle warning:', warning)
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--tree', type=Path, required=True, help='staged folder (…/The Order 1886) from the CI artifact')
    parser.add_argument('--version', default='', help='tar name stamp, e.g. v0.2.22')
    parser.add_argument('--fsr4', type=Path, default=None, help='bin/fsr4 of a previous package (FSR 4 v07 bundle)')
    parser.add_argument('--music', type=Path, default=None, help='music/ of a previous package')
    parser.add_argument('--extra', type=Path, default=None, help='release-repo documents merged in before the manifest is rebuilt')
    parser.add_argument('--out', type=Path, default=Path('.'), help='where to write tar.gz + .sha256')
    args = parser.parse_args()

    tree = args.tree.resolve()
    if tree.name != ROOT_FOLDER or not tree.is_dir():
        raise SystemExit(f'--tree must be a folder named {ROOT_FOLDER!r}: {tree}')
    manifest_path = tree / 'package-manifest.json'
    if not manifest_path.is_file():
        raise SystemExit('the CI artifact has no package-manifest.json; run the Linux package workflow first')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))

    # 1. Verify the CI's own entries before touching anything: a corrupt download stops here.
    problems = []
    # The upstream packager writes the manifest while its GO-BUILD-INCOMPLETE.txt marker still
    # exists and removes the marker after the smoke test, so the CI manifest lists a file that
    # is gone on purpose. The file list is rebuilt below anyway.
    manifest['files'] = [entry for entry in manifest['files'] if entry['path'] != 'GO-BUILD-INCOMPLETE.txt']
    for entry in manifest['files']:
        path = tree / entry['path']
        if not path.is_file():
            problems.append(f'manifest entry missing on disk: {entry["path"]}')
        elif sha256(path) != entry['sha256']:
            problems.append(f'hash mismatch against the CI manifest: {entry["path"]}')
    if problems:
        for problem in problems:
            print('PACKAGE PROBLEM:', problem, file=sys.stderr)
        return 1

    # 2. Merge.
    for source, target, label in ((args.fsr4, tree / 'bin' / 'fsr4', 'FSR 4 bundle'),
                                  (args.music, tree / 'music', 'music'),
                                  (args.extra, tree, 'release documents')):
        if source is not None:
            print(f'merged {copy_tree(source.resolve(), target)} files: {label}')

    # 3. Content rules.
    for relative in REQUIRED:
        if not (tree / relative).is_file():
            problems.append(f'missing required file: {relative}')
    fsr4 = tree / 'bin' / 'fsr4'
    if not fsr4.is_dir():
        problems.append('bin/fsr4/ is absent (pass --fsr4): the FSR 4 provider would fall back to FSR 3.1 everywhere')
    elif not (fsr4 / 'LICENSE-FSR4-v07.txt').is_file():
        problems.append('bin/fsr4/ present without LICENSE-FSR4-v07.txt')
    if (tree / 'user').exists():
        problems.append('user/ must not ship (settings and saves are created beside the launcher)')
    for path in sorted(tree.rglob('*')):
        if path.is_file() and path.suffix in FORBIDDEN_SUFFIXES:
            problems.append(f'Windows-only artifact shipped: {path.relative_to(tree).as_posix()}')
    problems += bundle_check(tree)
    if problems:
        for problem in problems:
            print('PACKAGE PROBLEM:', problem, file=sys.stderr)
        return 1
    print('bundle check: OK (every non-system library resolves inside the package)')

    # 4. Manifest over the merged tree; the CI's build metadata is kept.
    manifest['files'] = [{'path': p.relative_to(tree).as_posix(), 'sha256': sha256(p)}
                         for p in sorted(tree.rglob('*'))
                         if p.is_file() and p.name != 'package-manifest.json']
    manifest['platform'] = 'linux-x86_64'
    if args.version:
        manifest['version'] = args.version
    manifest['finalized_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

    suffix = f'-{args.version}' if args.version else ''
    args.out.mkdir(parents=True, exist_ok=True)
    archive = args.out / f'order1886-linux-x86_64{suffix}.tar.gz'
    with tarfile.open(archive, 'w:gz', compresslevel=6) as tar:
        tar.add(tree, arcname=ROOT_FOLDER, recursive=True)
    digest = sha256(archive)
    archive.with_suffix(archive.suffix + '.sha256').write_text(f'{digest}  {archive.name}\n', encoding='ascii')
    print(f'files: {len(manifest["files"]) + 1}, archive: {archive}, sha256: {digest}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
