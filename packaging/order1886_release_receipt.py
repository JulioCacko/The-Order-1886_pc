"""Write release-verification.json for a GitHub release of the Go launcher.

The in-launcher updater (launcher-go/internal/updates/release.go) downloads this receipt and
trusts the archive only when its name, size and SHA-256 match it, so the receipt is computed from
the archives themselves rather than typed in:

    python packaging/order1886_release_receipt.py --tag v0.2.0 \
        --windows out/release-assets/order1886-go-windows.zip \
        --linux out/release-assets/order1886-linux-x86_64.tar.gz --workflow-run 123 \
        --check native_tests="56 pass" --out out/release-assets/release-verification.json

It refuses a package built from a dirty tree (the updater rejects it), Windows and Linux packages
built from different revisions, and a tag the updater would not recognise.
"""
import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import tarfile
import zipfile
from pathlib import Path

UPDATE_ABI = 'order1886-update-2'
TAG = re.compile(r'^v[0-9]+\.[0-9]+\.[0-9]+(-go-preview\.[0-9]+)?$')  # release.go releaseTag


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def zip_json(path, suffix):
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.endswith(suffix)]
        if len(names) != 1:
            raise SystemExit(f'{path}: expected one {suffix}, found {names}')
        return json.loads(z.read(names[0]).decode('utf-8-sig'))


def tar_json(path, suffix):
    with tarfile.open(path) as t:
        members = [m for m in t.getmembers() if m.name.endswith(suffix)]
        if len(members) != 1:
            raise SystemExit(f'{path}: expected one {suffix}, found {[m.name for m in members]}')
        return json.loads(t.extractfile(members[0]).read().decode('utf-8-sig'))


def receipt(tag, windows, linux, workflow_run, checks, now=None):
    if not TAG.match(tag):
        raise SystemExit(f'{tag}: the updater only recognises vX.Y.Z or vX.Y.Z-go-preview.N')
    runtime = zip_json(windows, 'bin/runtime-build.json')
    if runtime.get('source_dirty') is not False:
        raise SystemExit('Windows runtime was built from a dirty tree; build from an LF checkout')
    linux_manifest = tar_json(linux, 'package-manifest.json')
    linux_revision = linux_manifest.get('source_revision') or linux_manifest.get(
        'runtime_build', {}).get('source_revision')
    if linux_revision != runtime['source_revision']:
        raise SystemExit(f'revisions differ: Windows {runtime["source_revision"]}, '
                         f'Linux {linux_revision}')
    linux_runtime = linux_manifest.get('runtime_sha256') or linux_manifest.get(
        'runtime_build', {}).get('runtime_sha256')
    archive_sha, archive_bytes = sha256(windows), Path(windows).stat().st_size
    return {
        'tag': tag,
        'source_revision': runtime['source_revision'],
        'published_utc': (now or dt.datetime.now(dt.timezone.utc)).isoformat(),
        'update_abi': UPDATE_ABI,
        'archive': Path(windows).name,
        'archive_sha256': archive_sha,
        'archive_bytes': archive_bytes,
        'runtime_sha256': runtime['runtime_sha256'],
        'runtime_build': runtime,
        'windows': {'asset': Path(windows).name, 'sha256': archive_sha, 'bytes': archive_bytes},
        'linux': {
            'asset': Path(linux).name,
            'sha256': sha256(linux),
            'bytes': Path(linux).stat().st_size,
            'source_revision': linux_revision,
            'runtime_sha256': linux_runtime,
            'workflow_run': workflow_run,
        },
        'checks': checks,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--tag', required=True)
    parser.add_argument('--windows', required=True, type=Path)
    parser.add_argument('--linux', required=True, type=Path)
    parser.add_argument('--workflow-run', required=True, help='run id of the Linux package build')
    parser.add_argument('--check', action='append', default=[], metavar='NAME=RESULT')
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(argv)
    checks = dict(item.split('=', 1) for item in args.check)
    data = receipt(args.tag, args.windows, args.linux, args.workflow_run, checks)
    args.out.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    print(f'{args.out}: {data["archive"]} {data["archive_bytes"]} bytes sha256 '
          f'{data["archive_sha256"]} at {data["source_revision"][:7]}')


if __name__ == '__main__':
    sys.exit(main())
