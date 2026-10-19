#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Write a hash-bound receipt after a successful local native runtime build."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def command(*args):
    return subprocess.check_output(args, cwd=ROOT, text=True, encoding='utf-8').strip()


def main():
    runtime = Path(sys.argv[1]).resolve()
    with runtime.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    paths = command('git', 'ls-files', '--cached', '--others', '--exclude-standard',
                    '--', 'src', 'gpu', 'build.sh', 'msys2-env.sh').splitlines()
    sources = hashlib.sha256()
    for name in sorted(set(paths)):
        path = ROOT / name
        if path.is_file():
            sources.update(name.encode('utf-8') + b'\0')
            sources.update(hashlib.sha256(path.read_bytes()).digest())
    receipt = {
        'game_profile': 'order1886',
        'runtime_abi': 'order1886-native-1',
        'prepared_format': 'PS4BOOT5',
        'renderer_profile': 'native-ps4',
        'shader_cache_abi': 'native-ps4-v1',
        'readback_policies': ['relaxed','precise','selective'],
        'runtime_sha256': digest,
        'source_revision': command('git', 'rev-parse', 'HEAD'),
        'source_dirty': bool(command('git', 'status', '--porcelain', '--untracked-files=normal')),
        'source_files_sha256': sources.hexdigest(),
        'submodules': command('git', 'submodule', 'status', '--recursive').splitlines(),
        'compiler': command('clang' if sys.platform == 'win32' else os.environ.get('CC', 'cc'),
                            '--version').splitlines()[0],
        'build_command': ['C:/msys64/usr/bin/bash.exe' if sys.platform == 'win32' else 'bash',
                          'build.sh'],
        'built_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    output = runtime.with_name('runtime-build.json')
    output.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(f'Build identity: {output} | SHA256 {digest}')


if __name__ == '__main__':
    main()
