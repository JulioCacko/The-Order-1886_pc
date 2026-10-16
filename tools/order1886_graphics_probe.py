#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Reproduce graphics failures with isolated cold caches and optional native dumps."""
from __future__ import annotations

import argparse
import datetime as dt
import math
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import order1886 as order


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
        prepared = order.prepare_game(game, user / 'prepared', frame_rate=args.frame_rate)
        settings = {'display_mode': args.display_mode, 'vsync': True,
                    'show_fps': args.show_fps, 'presentation_filter': args.presentation_filter,
                    'frame_rate': args.frame_rate}
        order.write_runtime_config(user, settings)
        order.save_backup.backup(user)
        output.mkdir(parents=True)
        cache = output / 'gpu'
        cache.mkdir()
        env = order.runtime_environment(runtime, user, settings)
        env['ORDER1886_GPU_USER_DIR'] = str(cache)
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
                  'frame_rate_profile': prepared.get('frame_rate_profile'), 'command': command,
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
        order.write_json(record, report)
        print(f'{report["status"]}; exit {report["exit_code"]}. Captures require visual verification.', flush=True)
        return report['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
