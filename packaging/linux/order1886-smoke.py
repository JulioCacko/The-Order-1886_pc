#!/usr/bin/env python3
"""Relocate and verify a Linux bundle without starting gameplay."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--game-dir', type=Path)
    args = parser.parse_args()
    if sys.platform != 'linux':
        parser.error('Linux verification requires Linux; use xvfb-run for headless GUI checks')
    args.output.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='Portable Linux ç ', dir=args.output.resolve()))
    package = work / 'The Order 1886'
    shutil.copytree(args.package.resolve(), package)
    if (package / 'user').exists():
        raise ValueError('Verify a fresh package without player state')
    checks = {}
    manifest = json.loads((package / 'package-manifest.json').read_text())
    mismatches = []
    for name, expected in manifest['files'].items():
        path = (package / name).resolve()
        if not path.is_relative_to(package) or not path.is_file() or digest(path) != expected:
            mismatches.append(name)
    checks['manifest'] = {'passed': not mismatches, 'files': len(manifest['files']), 'errors': mismatches}
    if mismatches:
        raise ValueError('Package hash mismatch: ' + ', '.join(mismatches))
    runtime = package / 'bin/order1886-runtime'
    receipt = json.loads((package / 'bin/runtime-build.json').read_text())
    checks['native_identity'] = {'passed': receipt['game_profile'] == 'order1886' and
        receipt['runtime_sha256'] == digest(runtime) and
        receipt['renderer_sha256'] == digest(package / 'bin/gpu/libps4gpu.so')}
    if not checks['native_identity']['passed']:
        raise ValueError('Native runtime/renderer identity mismatch')
    home = work / 'Home'
    home.mkdir()
    cwd = work / 'Different working directory'
    cwd.mkdir()
    env = {key: value for key, value in os.environ.items()
           if key in ('DISPLAY', 'XAUTHORITY', 'XDG_RUNTIME_DIR', 'LANG', 'LC_ALL')}
    env.update(PATH='/usr/bin:/bin', HOME=str(home),
               LD_LIBRARY_PATH=str(package / 'bin/gpu') + ':' + str(package / 'bin/lib'))
    linked = subprocess.check_output(['ldd', str(runtime)], env=env, text=True)
    outside = []
    for name, path in re.findall(r'^\s*(\S+)\s+=>\s+(/\S+)\s+\(', linked, re.MULTILINE):
        if re.match(r'^lib(?:c|m|pthread|dl|rt|resolv|util)\.so|^libnss_', name):
            continue
        if not Path(path).resolve().is_relative_to(package) and not path.startswith('/usr/lib/wsl/'):
            outside.append(path)
    checks['native_dependencies'] = {'passed': not outside and 'not found' not in linked,
                                      'outside_package': outside}
    if not checks['native_dependencies']['passed']:
        raise ValueError('Native dependency closure is incomplete: ' + linked)

    def run(name, command, expected=(0,)):
        try:
            result = subprocess.run(list(map(str, command)), cwd=cwd, env=env, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
            (work / (name + '.log')).write_text(result.stdout)
            checks[name] = {'passed': result.returncode in expected, 'exit_code': result.returncode}
        except subprocess.TimeoutExpired as error:
            (work / (name + '.log')).write_bytes(error.output or b'')
            checks[name] = {'passed': False, 'error': 'timeout'}

    launcher = package / 'The Order 1886'
    state = package / 'user/order1886'
    run('native_help', [runtime, '--help'], (0, 2))
    run('native_info', [runtime, '--runtime-info'])
    run('gui', [launcher, '--state-dir', state, '--smoke-test'])
    run('direct_play_gui', [package / 'Play The Order 1886', '--state-dir', state, '--smoke-test'])
    run('missing_game', [launcher, '--run-backend', '--game-dir', work / 'Missing Game',
        '--state-dir', state, '--prepare-only'], (2,))
    if args.game_dir:
        for rate in (30, 60):
            run(f'prepare_{rate}', [launcher, '--run-backend', '--game-dir', args.game_dir.resolve(),
                '--state-dir', state, '--frame-rate', rate, '--prepare-only'])
    report = {'scope': 'Linux host/bootstrap/CPU preparation; no gameplay or GPU acceptance',
              'package': str(args.package.resolve()), 'tested_copy': str(package),
              'checks': checks, 'passed': all(check['passed'] for check in checks.values())}
    path = work / 'smoke-report.json'
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(path)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
