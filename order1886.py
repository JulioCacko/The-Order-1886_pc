#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""The Order: 1886 launch path using the repository's native PS4 loader.

Prepared images contain PS4 code; optional timing changes are hash-bound derived patches.
State and configuration belong to this title.
An import audit or a successful process exit is never treated as gameplay proof.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
INSTALL_ROOT = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else ROOT
SCRIPTS = ROOT / 'scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import prepare
import link_modules
import save_backup
import order1886_frame_rate as timing
import order1886_display as display
import order1886_mods as mods

TITLE_ID = 'CUSA00076'
RUNTIME_ABI = 'order1886-native-1'
SHADER_CACHE_ABI = 'native-ps4-v1'
# OrbisSystemParamLanguage: pt is Brazilian Portuguese; zh is Simplified Chinese.
SYSTEM_LANGUAGES = {'en': 1, 'ru': 8, 'ar': 21, 'es': 3, 'pt': 17, 'fr': 2,
                    'de': 4, 'it': 5, 'pl': 16, 'tr': 19, 'zh': 11, 'ja': 0, 'ko': 9}
REQUIRED_FILES = ('eboot.bin', 'sce_sys/param.sfo', 'sce_module/libc.prx', 'sce_module/libSceFios2.prx')


def emit_status(message, *, error=False, fallback=None):
    """A detached console must not replace the runtime's result or its diagnostics."""
    primary, secondary = ('stderr', 'stdout') if error else ('stdout', 'stderr')
    failed = False
    for name in (primary, secondary):
        stream = getattr(sys, name)
        if stream is None:
            failed = True
            continue
        try:
            print(message, file=stream, flush=True)
            if not failed:
                return
            break
        except (OSError, ValueError):
            # Retire the dead stream so Python's final flush cannot change exit 0/23 to 120.
            failed = True
            for other in ('stdout', 'stderr'):
                if getattr(sys, other) is stream:
                    setattr(sys, other, None)
            if hasattr(stream, 'close'):
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass
    if failed and fallback is not None:
        if hasattr(fallback, 'write'):
            fallback.write(message + '\n')
            fallback.flush()
        else:
            path = Path(fallback)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('a', encoding='utf-8') as log:
                log.write(message + '\n')


def default_game_dir():
    relative = Path('ShadPs4Plus-PkgExtractor-1.1-windows') / TITLE_ID
    for base in (INSTALL_ROOT, INSTALL_ROOT.parent, INSTALL_ROOT.parent.parent):
        if (base / relative / 'eboot.bin').is_file():
            return base / relative
    return INSTALL_ROOT / relative


def inspect_game(game):
    game = Path(game).expanduser().resolve()
    for name in REQUIRED_FILES:
        file = game / name
        if not file.is_file() or file.stat().st_size == 0:
            raise ValueError(f'Missing or empty game file: {file}')
    metadata = prepare.load_sfo(game / 'sce_sys/param.sfo')
    if metadata.get('TITLE_ID') != TITLE_ID:
        raise ValueError(f'Expected {TITLE_ID} (The Order: 1886), found {metadata.get("TITLE_ID", "unknown title")}')
    if not (game / '_data').is_dir() or not (game / 'archivemap.bin').is_file():
        raise ValueError('The Order game content is incomplete: _data and archivemap.bin are required.')
    return metadata


def find_runtime(explicit=None):
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f'Runtime executable not found: {path}')
        build = runtime_identity(path)['build']
        if not build or build.get('game_profile') != 'order1886' or build.get('runtime_abi') != RUNTIME_ABI:
            raise ValueError('Selected executable is not a verified dedicated Order runtime. Rebuild order1886-runtime.exe.')
        return path
    name = 'order1886-runtime.exe' if os.name == 'nt' else 'order1886-runtime'
    bases = (INSTALL_ROOT,) if getattr(sys, 'frozen', False) else tuple(dict.fromkeys((INSTALL_ROOT, ROOT)))
    candidates = [base / folder / name for base in bases
                  for folder in ('bin', 'out')]
    for candidate in candidates:
        if candidate.is_file():
            return find_runtime(candidate)
    return None


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def runtime_identity(runtime):
    runtime = Path(runtime).resolve()
    digest = sha256(runtime)
    try:
        build = json.loads(runtime.with_name('runtime-build.json').read_text(encoding='utf-8'))
        if not isinstance(build, dict) or build.get('runtime_sha256') != digest:
            build = None
    except (OSError, ValueError):
        build = None
    return {'runtime': str(runtime), 'runtime_sha256': digest, 'build': build}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def prepare_game(game, out, frame_rate=30, aspect_ratio='original'):
    game, out = Path(game).resolve(), Path(out).resolve()
    metadata = inspect_game(game)
    # Prevent accidental writes to the extracted game, even with custom CLI arguments.
    if out == game or game in out.parents:
        raise ValueError('Prepared images must be stored outside the game folder.')
    profile = timing.validate_source(game / 'eboot.bin', frame_rate, metadata)
    display_profile = display.validate_source(game / 'eboot.bin', aspect_ratio, metadata)
    fingerprint = {name: sha256(game / name) for name in REQUIRED_FILES}
    for name in ('prepare.py', 'link_modules.py', 'link_libc.py', 'order1886_frame_rate.py', 'order1886_display.py'):
        fingerprint['tool/' + name] = sha256(SCRIPTS / name)
    fingerprint.update(frame_rate=profile['engine_fps'], host_fps_limit=profile['host_fps_limit'],
                       frame_rate_recipe_sha256=profile['recipe_sha256'], runtime_abi=RUNTIME_ABI,
                       preparation_schema=3, aspect_ratio=aspect_ratio,
                       display_recipe_sha256=display_profile['recipe_sha256'])
    manifest = out / 'prepared.json'
    try:
        previous = json.loads(manifest.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        previous = {}
    image = out / 'boot-linked.bin'
    if (previous.get('inputs') == fingerprint and previous.get('game') == str(game)
            and image.is_file() and previous.get('image_sha256') == sha256(image)
            and (frame_rate == 30 or previous.get('frame_rate_profile', {}).get('applied') is True)
            and (aspect_ratio == 'original' or previous.get('display_profile', {}).get('applied') is True)):
        emit_status('Prepared image verified; reusing cached image.', fallback=out.parent / 'logs/backend.log')
        return previous
    out.mkdir(parents=True, exist_ok=True)
    # Invalidate before writing, so interrupted preparation cannot reuse a partial image.
    manifest.unlink(missing_ok=True)
    prepare.prepare(game, out)
    profile = timing.apply_prepared(out / 'boot.bin', profile)
    display_profile = display.apply_prepared(out / 'boot.bin', display_profile)
    link_modules.link(game, out)
    result = {'game': str(game), 'title_id': metadata['TITLE_ID'], 'inputs': fingerprint,
              'frame_rate_profile': profile,
              'display_profile': display_profile,
              'image_sha256': sha256(image), 'status': 'prepared; gameplay unverified'}
    write_json(manifest, result)
    return result


def runtime_environment(runtime, user, settings=None, inherited=None):
    runtime, user = Path(runtime).resolve(), Path(user).resolve()
    settings = settings or {}
    frame_rate = timing.validate_frame_rate(settings.get('frame_rate', 30))
    system_language = settings.get('system_language', 1)
    if type(system_language) is not int or not 0 <= system_language <= 29:
        raise ValueError('System language must be an integer from 0 to 29')
    source = os.environ if inherited is None else inherited
    env = {k: v for k, v in source.items()
           if not k.upper().startswith('ORDER1886_') or k == 'ORDER1886_DIAG_RESOURCE_SHARPS'}
    env.update({
        'ORDER1886_CONFIG': str(user / 'runtime.ini'), 'ORDER1886_USER_DIR': str(user),
        'ORDER1886_GPU_USER_DIR': str(user / 'gpu' / SHADER_CACHE_ABI), 'ORDER1886_GAME_PROFILE': 'order1886',
        'ORDER1886_FPS_LIMIT': str(frame_rate),
        'ORDER1886_LANGUAGE': str(system_language),
        # Reuse validated cached pipelines before playback rather than compiling during it.
        'ORDER1886_PIPELINE_BINARIES': '0', 'ORDER1886_BACKGROUND_WARMUP': '0',
        'ORDER1886_PARALLEL_WARMUP': '0',
        # Keep unverified speculative SRT work off the normal Order launch path.
        'ORDER1886_PREP_WORKERS': '0',
        'ORDER1886_SETTINGS_MENU': '0',
        'ORDER1886_VBLANK_HZ': '60',
        'ORDER1886_STREAM_MEMORY': 'cached', 'PYTHONIOENCODING': 'utf-8',
    })
    env['PATH'] = str(runtime.parent) + os.pathsep + env.get('PATH', '')
    if os.name == 'nt' and not getattr(sys, 'frozen', False) and ROOT / 'out' in runtime.parents:
        # Source builds link CLANG64 DLLs. Portable packages carry their own closure in bin/.
        dependencies = Path(source.get('MSYS2_ROOT', r'C:\msys64')) / 'clang64' / 'bin'
        if dependencies.is_dir():
            env['PATH'] = str(runtime.parent) + os.pathsep + str(dependencies) + os.pathsep + source.get('PATH', '')
    icon = user / 'window_icon.bmp'
    if icon.is_file():
        env['ORDER1886_WINDOW_ICON'] = str(icon)
    return env


def write_runtime_config(user, settings):
    sensitivity = settings.get('mouse_sensitivity', 100)
    if type(sensitivity) is not int or not 10 <= sensitivity <= 500:
        raise ValueError('Mouse sensitivity must be an integer from 10 to 500 percent')
    mode = settings.get('display_mode', 'windowed')
    if mode not in ('windowed', 'borderless', 'fullscreen'):
        raise ValueError('Invalid display mode')
    presentation_filter = settings.get('presentation_filter', 'fsr1')
    if presentation_filter not in ('linear', 'fsr1'):
        raise ValueError('Invalid presentation filter')
    frame_rate = timing.validate_frame_rate(settings.get('frame_rate', 30))
    values = {'display_mode': mode, 'vsync': int(bool(settings.get('vsync', True))),
              'show_fps': int(bool(settings.get('show_fps', False))), 'fps_limit': frame_rate,
              'render_resolution': 'native', 'presentation_filter': presentation_filter, 'frames_queued': 1,
              'overlay_fps': 1, 'overlay_frametime': 1, 'overlay_gpu': 1,
              'mouse_look': int(bool(settings.get('mouse_look', True))),
              'mouse_sensitivity': sensitivity,
              'mouse_invert_y': int(bool(settings.get('mouse_invert_y', False)))}
    Path(user).mkdir(parents=True, exist_ok=True)
    (Path(user) / 'runtime.ini').write_text(
        '# The Order: 1886 requested settings; applied timing recipe is recorded in prepared.json.\n'
        + ''.join(f'{k}={v}\n' for k, v in values.items()), encoding='utf-8')


def build_command(runtime, image, game, user, check_imports=False):
    command = [str(Path(runtime).resolve()), str(Path(image).resolve()),
               '--app0', str(Path(game).resolve()), '--user', str(Path(user).resolve()), '--timeout', '0']
    if check_imports:
        command.append('--check-imports')
    return command


def request_runtime_close(pid):
    """Request the runtime's normal window close path before considering force."""
    if os.name != 'nt':
        import signal
        try:
            os.kill(pid, signal.SIGTERM)
            return True
        except ProcessLookupError:
            return False
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    sent = False

    @callback_type
    def close_window(window, _):
        nonlocal sent
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
        if owner.value == pid and user32.PostMessageW(window, 0x0010, 0, 0):
            sent = True
        return True

    user32.EnumWindows(close_window, 0)
    return sent


def run_process(command, env, log, timeout=0, stop_file=None, stop_grace_seconds=5):
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    started = time.monotonic()
    stop_file = Path(stop_file) if stop_file else None
    timed_out = stop_requested = forced_stop = False
    with Path(log).open('w', encoding='utf-8') as output:
        output.write('Command: ' + json.dumps(command) + '\n')
        output.flush()
        if stop_file and stop_file.exists():
            output.write('Cancelled before runtime start.\n')
            return {'exit_code': 130, 'timed_out': False, 'stop_requested': True,
                    'forced_stop': False, 'elapsed_seconds': 0}
        child = subprocess.Popen(command, cwd=str(Path(env['ORDER1886_USER_DIR'])), env=env,
                                 stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                 creationflags=flags)
        try:
            emit_status(f'Runtime started (PID {child.pid})', fallback=output)
            while child.poll() is None:
                if stop_file and stop_file.exists():
                    stop_requested = True
                    request_runtime_close(child.pid)
                    try:
                        child.wait(timeout=stop_grace_seconds)
                    except subprocess.TimeoutExpired:
                        forced_stop = True
                        child.kill()
                        child.wait()
                    emit_status('Shutdown: forced' if forced_stop else 'Shutdown: graceful', fallback=output)
                    break
                if timeout and time.monotonic() - started >= timeout:
                    timed_out = forced_stop = True
                    child.kill()
                    child.wait()
                    break
                try:
                    child.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    pass
            code = 124 if timed_out else 130 if stop_requested else child.returncode
        except BaseException:
            child.kill()
            child.wait()
            raise
    return {'exit_code': code, 'runtime_exit_code': child.returncode, 'timed_out': timed_out,
            'stop_requested': stop_requested, 'forced_stop': forced_stop,
            'elapsed_seconds': round(time.monotonic() - started, 3)}


@contextlib.contextmanager
def session_lock(user):
    """OS-owned lock releases after a crash; prevent concurrent preparation and save writes."""
    file = (Path(user) / 'session.lock').open('a+b')
    try:
        file.seek(0)
        if os.name == 'nt':
            import msvcrt
            if file.read(1) == b'':
                file.write(b'0')
                file.flush()
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        file.close()
        raise RuntimeError('The Order is already running or being prepared.') from error
    try:
        yield
    finally:
        file.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-dir', type=Path, default=default_game_dir())
    parser.add_argument('--runtime', type=Path)
    parser.add_argument('--stop-file', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--state-dir', type=Path, default=INSTALL_ROOT / 'user' / 'order1886')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--prepare-only', action='store_true')
    action.add_argument('--check-imports', action='store_true')
    parser.add_argument('--timeout', type=float, default=0, help='Host watchdog in seconds; 0 waits until exit')
    parser.add_argument('--display-mode', choices=['windowed', 'borderless', 'fullscreen'], default='windowed')
    parser.add_argument('--presentation-filter', choices=['linear', 'fsr1'], default='fsr1',
                        help='Output scaling filter; game rendering and timing stay native')
    parser.add_argument('--frame-rate', type=int, choices=[30, 60], default=30,
                        help='30 is the native baseline; 60 is experimental with known QTE risks')
    parser.add_argument('--system-language', type=int, choices=range(30), default=1,
                        help='PS4 system language ID; game requires installed language assets (default: English US)')
    parser.add_argument('--aspect-ratio', choices=['original', '16:9'], default='original',
                        help='Experimental full-screen 16:9 or original cinematic aspect; requires restart')
    parser.add_argument('--vsync', type=int, choices=[0, 1], default=1)
    parser.add_argument('--show-fps', type=int, choices=[0, 1], default=0)
    parser.add_argument('--mouse-look', type=int, choices=[0, 1], default=1)
    parser.add_argument('--mouse-sensitivity', type=int, default=100,
                        help='Mouse-to-stick sensitivity, 10 to 500 percent (default: 100)')
    parser.add_argument('--mouse-invert-y', type=int, choices=[0, 1], default=0)
    parser.add_argument('--mods-dir', default='', help='Folder containing explicitly selected asset mod folders')
    parser.add_argument('--mods-enabled', type=int, choices=[0, 1], default=0)
    parser.add_argument('--mods-order', default='[]', help='JSON list of enabled mod folder names; later entries win')
    args = parser.parse_args(argv)
    if not 10 <= args.mouse_sensitivity <= 500:
        parser.error('--mouse-sensitivity must be from 10 to 500')
    if not math.isfinite(args.timeout) or args.timeout < 0:
        parser.error('--timeout must be a finite nonnegative number')
    try:
        args.mods_dir = str(mods.resolve_root(args.mods_dir, ROOT))
        game, user = mods.safe_path(args.game_dir), mods.safe_path(args.state_dir)
        mods.safe_path(user / 'session.lock')
        if args.mods_dir:
            mod_root = mods.safe_path(args.mods_dir)
            if user == mod_root or mod_root in user.parents:
                raise ValueError('State directory must be outside the mod source folder.')
    except (OSError, ValueError) as error:
        emit_status(f'The Order: {error}', error=True)
        return 2
    if user == game or game in user.parents:
        emit_status('State directory must be outside the game folder.', error=True)
        return 2
    diagnostic_log = user / 'logs/backend.log'
    try:
        user.mkdir(parents=True, exist_ok=True)
        with session_lock(user):
            mod_order = json.loads(args.mods_order)
            mods.validate_config(args.mods_dir, bool(args.mods_enabled), mod_order)
            metadata = inspect_game(game)
            if args.stop_file and args.stop_file.exists():
                emit_status('Cancelled before preparation.', fallback=diagnostic_log)
                return 130
            emit_status(f'{metadata["TITLE"]} | {metadata["TITLE_ID"]} | APP_VER {metadata.get("APP_VER")} | VERSION {metadata.get("VERSION")}', fallback=diagnostic_log)
            runtime = None if args.prepare_only else find_runtime(args.runtime)
            if not args.prepare_only and runtime is None:
                raise ValueError('Order runtime not found in this installation. Build build.sh or explicitly select a runtime in Settings.')
            if args.frame_rate == 60:
                emit_status(timing.WARNING, fallback=diagnostic_log)
            if args.aspect_ratio == '16:9':
                emit_status(display.WARNING, fallback=diagnostic_log)
            prepared = prepare_game(game, user / 'prepared', frame_rate=args.frame_rate, aspect_ratio=args.aspect_ratio)
            if args.aspect_ratio == '16:9' and not (prepared.get('display_profile', {}).get('applied') is True
                    and prepared['display_profile'].get('source_verified') is True
                    and prepared['display_profile'].get('recipe_sha256') == display.recipe_sha256('16:9')):
                raise ValueError('Full-screen 16:9 requires a verified prepared aspect recipe')
            if args.frame_rate == 60 and not (prepared.get('frame_rate_profile', {}).get('applied') is True
                    and prepared['frame_rate_profile'].get('source_verified') is True
                    and prepared['frame_rate_profile'].get('engine_fps') == 60
                    and prepared['frame_rate_profile'].get('host_fps_limit') == 60
                    and prepared['frame_rate_profile'].get('recipe_sha256') == timing.recipe_sha256(60)):
                raise ValueError('Experimental 60 FPS requires a verified prepared timing recipe')
            if args.prepare_only:
                return 0
            write_runtime_config(user, vars(args))
            # Use the supplied official emblem for the runtime window as well.
            try:
                from PIL import Image
                bundled_icon = Path(getattr(sys, '_MEIPASS', ROOT)) / 'launcher/order1886/app-icon.png'
                with Image.open(bundled_icon if bundled_icon.is_file() else game / 'sce_sys/icon0.png') as icon:
                    icon.convert('RGB').save(user / 'window_icon.bmp')
            except (ImportError, OSError):
                pass
            if not args.check_imports:
                save_backup.backup(user)
            env = runtime_environment(runtime, user, vars(args))
            mode = 'imports' if args.check_imports else 'boot'
            stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
            logs = user / 'logs'
            logs.mkdir(exist_ok=True)
            log = logs / f'{stamp}-{mode}.log'
            mounted_game = mods.build_overlay(game, user, args.mods_dir,
                                             bool(args.mods_enabled) and not args.check_imports, mod_order)
            command = build_command(runtime, user / 'prepared/boot-linked.bin', mounted_game, user, args.check_imports)
            report = {'mode': mode, 'started_utc': stamp, **runtime_identity(runtime),
                      'game': str(game), 'mounted_game': str(mounted_game),
                      'mods': {'enabled': bool(args.mods_enabled) and not args.check_imports,
                               'folder': args.mods_dir, 'order': mod_order},
                      'title_id': TITLE_ID, 'image_sha256': prepared['image_sha256'],
                      'game_metadata': {key: metadata.get(key) for key in
                                        ('TITLE', 'TITLE_ID', 'APP_VER', 'VERSION', 'INSTALL_DIR_SAVEDATA', 'SYSTEM_VER')},
                      'shader_cache_abi': SHADER_CACHE_ABI,
                      'log': str(log), 'status': 'running', 'gameplay_verified': False,
                      'command': command, 'config_sha256': sha256(user / 'runtime.ini'),
                      'runtime_environment': {k: v for k, v in env.items() if k.startswith('ORDER1886_')},
                       'frame_rate_profile': prepared.get('frame_rate_profile'),
                       'display_profile': prepared.get('display_profile'),
                       'settings': {'display_mode': args.display_mode, 'vsync': args.vsync,
                                    'show_fps': args.show_fps, 'presentation_filter': args.presentation_filter,
                                    'frame_rate': args.frame_rate, 'fps_limit': args.frame_rate,
                                    'aspect_ratio': args.aspect_ratio, 'system_language': args.system_language}}
            write_json(logs / 'last-run.json', report)
            emit_status(f'Log: {log}', fallback=diagnostic_log)
            emit_status(f'Runtime: {report["runtime"]} | SHA256 {report["runtime_sha256"]}', fallback=diagnostic_log)
            emit_status('Experimental compatibility run. Gameplay and performance are not yet verified.', fallback=diagnostic_log)
            try:
                report.update(run_process(command, env, log, args.timeout or (60 if args.check_imports else 0), args.stop_file))
            except (OSError, KeyboardInterrupt) as error:
                report.update(status='interrupted' if isinstance(error, KeyboardInterrupt) else 'launch_failed',
                              exit_code=130 if isinstance(error, KeyboardInterrupt) else 2,
                              stop_reason=str(error) or 'Interrupted', timed_out=False)
                write_json(log.with_suffix('.json'), report)
                write_json(logs / 'last-run.json', report)
                emit_status(f'Runtime {report["status"]}: {report["stop_reason"]}', error=True, fallback=diagnostic_log)
                return report['exit_code']
            tail = log.read_text(encoding='utf-8', errors='replace')
            missing = re.search(r'Imports: (\d+) missing', tail)
            report['missing_imports'] = int(missing[1]) if missing else None
            stops = [line for line in tail.splitlines() if 'STOP:' in line or 'unresolved' in line.lower()]
            report['stop_reason'] = stops[-1] if stops else None
            report['status'] = ('timed_out' if report['timed_out'] else
                                'stopped' if report.get('stop_requested') else
                                'failed' if report['exit_code'] else 'process_exited')
            write_json(log.with_suffix('.json'), report)
            write_json(logs / 'last-run.json', report)
            if missing:
                emit_status(f'Import audit: {report["missing_imports"]} missing.', fallback=diagnostic_log)
            if report['stop_reason']:
                emit_status(report['stop_reason'], fallback=diagnostic_log)
            emit_status(f'Runtime {report["status"]}; exit {report["exit_code"]}. Log: {log}', fallback=diagnostic_log)
            return report['exit_code']
    except (OSError, ValueError, RuntimeError) as error:
        emit_status(f'The Order: {error}', error=True, fallback=diagnostic_log)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
