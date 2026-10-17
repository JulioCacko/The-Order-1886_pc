#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Reproduce graphics failures with isolated cold caches and optional native dumps."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import math
from pathlib import Path
import re
import struct
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import order1886 as order

PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def capture_identity(path):
    """Describe a captured frame file and verify its encoded dimensions when available."""
    path = Path(path)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        header = stream.read(24)
        if path.suffix.casefold() == '.png':
            if len(header) < 24 or header[:8] != PNG_SIGNATURE or header[12:16] != b'IHDR':
                raise ValueError(f'Frame capture is not a complete PNG: {path}')
            width, height = struct.unpack('>II', header[16:24])
            encoding = 'png'
        elif path.suffix.casefold() == '.raw':
            match = re.search(r'_(\d+)x(\d+)\.raw$', path.name, re.IGNORECASE)
            if not match:
                raise ValueError(f'Raw frame capture name does not include its dimensions: {path}')
            width, height = (int(value) for value in match.groups())
            if path.stat().st_size != width * height * 4:
                raise ValueError(f'Raw frame capture size does not match its dimensions: {path}')
            encoding = 'raw-32-bit'
        else:
            raise ValueError(f'Unsupported frame capture format: {path}')
        if not width or not height:
            raise ValueError(f'Frame capture has invalid dimensions: {path}')
        digest.update(header)
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return {'path': str(path.resolve()), 'sha256': digest.hexdigest(),
            'width': width, 'height': height, 'size_bytes': path.stat().st_size,
            'encoding': encoding}


def guest_frame_trace(path):
    """Summarize distinct guest render work from the runtime's optional raw trace."""
    path = Path(path)
    if not path.is_file():
        return None
    import order1886_frame_trace
    with path.open(newline='', encoding='utf-8') as source:
        result = order1886_frame_trace.summarize(csv.DictReader(source))
    return {'path': str(path.resolve()), 'sha256': order.sha256(path),
            'size_bytes': path.stat().st_size, 'summary': result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-dir', type=Path, default=order.default_game_dir())
    parser.add_argument('--runtime', type=Path)
    parser.add_argument('--state-dir', type=Path, default=ROOT / 'user/order1886')
    parser.add_argument('--output-dir', type=Path, required=True, help='New diagnostic directory')
    parser.add_argument('--timeout', type=float, default=45)
    parser.add_argument('--dump-shaders', action='store_true')
    parser.add_argument('--dump-frame', action='store_true')
    parser.add_argument('--frame-delay', type=float, default=0, help='Seconds after launch before requesting a frame')
    parser.add_argument('--display-mode', choices=['windowed', 'borderless', 'fullscreen'], default='windowed')
    parser.add_argument('--presentation-filter', choices=['linear', 'fsr1'], default='fsr1')
    parser.add_argument('--frame-rate', type=int, choices=[30, 60], default=30)
    parser.add_argument('--aspect-ratio', choices=['original', '16:9'], default='original')
    parser.add_argument('--frame-trace', action=argparse.BooleanOptionalAction, default=True,
                        help='record guest flips and summarize distinct render-work intervals')
    parser.add_argument('--show-fps', action='store_true')
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('--timeout must be finite and positive')
    if not math.isfinite(args.frame_delay) or args.frame_delay < 0:
        parser.error('--frame-delay must be finite and nonnegative')
    game, user, output = (p.resolve() for p in (args.game_dir, args.state_dir, args.output_dir))
    for path in (user, output):
        if path == game or game in path.parents:
            parser.error('State and diagnostics must remain outside the original game directory')
    if output.exists():
        parser.error('--output-dir must be new so previous captures cannot be overwritten')
    metadata = order.inspect_game(game)
    runtime = order.find_runtime(args.runtime)
    if runtime is None:
        parser.error('Build the dedicated Order runtime first')
    user.mkdir(parents=True, exist_ok=True)
    with order.session_lock(user):
        prepared = order.prepare_game(game, user / 'prepared', frame_rate=args.frame_rate,
                                      aspect_ratio=args.aspect_ratio)
        settings = {'display_mode': args.display_mode, 'vsync': True,
                    'show_fps': args.show_fps, 'presentation_filter': args.presentation_filter,
                    'frame_rate': args.frame_rate, 'aspect_ratio': args.aspect_ratio}
        order.write_runtime_config(user, settings)
        order.save_backup.backup(user)
        output.mkdir(parents=True)
        cache = output / 'gpu'
        cache.mkdir()
        env = order.runtime_environment(runtime, user, settings)
        env['ORDER1886_GPU_USER_DIR'] = str(cache)
        trace_path = output / 'frame-trace.csv'
        if args.frame_trace:
            env['ORDER1886_FRAME_TRACE'] = str(trace_path)
        capture_timer = None
        if args.dump_shaders:
            env['ORDER1886_DUMP_SHADERS'] = '1'
            env['ORDER1886_DIAG_RESOURCE_SHARPS'] = '1'
        if args.dump_frame:
            frames = output / 'frames'
            frames.mkdir()
            trigger = output / 'dump-frame.request'
            if args.frame_delay:
                capture_timer = threading.Timer(args.frame_delay, trigger.touch)
                capture_timer.daemon = True
            else:
                trigger.touch()
            env['ORDER1886_DUMP_DIR'] = str(frames)
            env['ORDER1886_FRAME_DUMP_TRIGGER'] = str(trigger)
        command = order.build_command(runtime, user / 'prepared/boot-linked.bin', game, user)
        log = output / 'native.log'
        record = output / 'run.json'
        report = {**order.runtime_identity(runtime), 'mode': 'graphics_probe',
                  'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                  'game': str(game), 'game_metadata': {key: metadata.get(key) for key in
                    ('TITLE', 'TITLE_ID', 'APP_VER', 'VERSION', 'INSTALL_DIR_SAVEDATA', 'SYSTEM_VER')},
                  'image_sha256': prepared['image_sha256'],
                  'frame_rate_profile': prepared.get('frame_rate_profile'),
                  'display_profile': prepared.get('display_profile'),
                  'internal_resolution': 'native',
                  'guest_frame_trace': None,
                  'frame_capture_identities': [], 'command': command,
                  'log': str(log), 'settings': settings, 'cache_state': 'new isolated cold cache',
                  'frame_capture_delay_seconds': args.frame_delay,
                  'runtime_environment': {k: v for k, v in env.items() if k.startswith('ORDER1886_')},
                  'status': 'running', 'gameplay_verified': False, 'rendering_verified': False}
        order.write_json(record, report)
        print(f'Graphics probe: {record}', flush=True)
        if capture_timer:
            capture_timer.start()
        try:
            report.update(order.run_process(command, env, log, args.timeout))
            report['status'] = 'timed_out' if report['timed_out'] else 'failed' if report['exit_code'] else 'process_exited'
        except BaseException as error:
            report.update(status='interrupted', error=str(error), exit_code=130)
            order.write_json(record, report)
            raise
        finally:
            if capture_timer:
                capture_timer.cancel()
                capture_timer.join()
        text = log.read_text(encoding='utf-8', errors='replace')
        report['stop_reason'] = next((line for line in text.splitlines() if 'STOP:' in line), None)
        report['guest_frame_trace'] = guest_frame_trace(trace_path) if args.frame_trace else None
        frames = output / 'frames'
        if frames.is_dir():
            report['frame_capture_identities'] = [capture_identity(path) for path in
                                                  sorted((*frames.glob('*.png'), *frames.glob('*.raw')))]
            dimensions = sorted({(frame['width'], frame['height'])
                                 for frame in report['frame_capture_identities']})
            report['captured_output_resolutions'] = [f'{width}x{height}'
                                                     for width, height in dimensions]
        order.write_json(record, report)
        print(f'{report["status"]}; exit {report["exit_code"]}. Captures require visual verification.', flush=True)
        return report['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
