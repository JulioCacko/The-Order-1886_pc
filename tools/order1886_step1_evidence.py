#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Matched on/off evidence for the step-1 graphics options.

Every variant is one graphics-probe run with the same capture delays and a new cold cache.
The first run is the baseline (launcher defaults) and a second baseline run measures the
run-to-run noise, so an image or frame-time difference is only meaningful above it.
Frame dumps are converted to PNG, desktop screenshots catch the overlay (which the
presenter draws after the dumped frame), and each run's native trace is summarised.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading

import numpy as np
from PIL import Image, ImageGrab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import order1886_perf_report as perf_report  # noqa: E402

PROBE = ROOT / 'tools' / 'order1886_graphics_probe.py'
OVERLAY_ALL = ['overlay_frametime=1', 'overlay_gpu=1', 'overlay_cpu=1', 'overlay_memory=1']
VARIANTS = {
    'baseline': [],
    'baseline-repeat': [],
    'output-1280x720': ['output_resolution=1280x720'],
    'output-2560x1440': ['output_resolution=2560x1440'],
    'sharpness-100': ['sharpness=100'],
    'anisotropy-16': ['anisotropy=16'],
    'overlay-none': ['overlay_frametime=0'],
    'overlay-all': OVERLAY_ALL,
    'frames-queued-2': ['frames_queued=2'],
    'frames-queued-0': ['frames_queued=0'],
    'async-shaders': ['async_shaders=1'],
    'background-warmup': ['background_warmup=1'],
    'parallel-warmup': ['parallel_warmup=1'],
    'deferred-readbacks': ['speculative_readbacks=1'],
    'fps-cap-45': ['fps_cap=45', 'in_game_menu=1'],
}
SHOW_FPS = {'overlay-none', 'overlay-all'}


def press(key):
    """Tap a key in the game window (Space is Cross in runtime_pad.c's default map)."""
    import ctypes
    user32 = ctypes.windll.user32
    found = []
    callback = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(
        lambda hwnd, _: (found.append(hwnd) if user32.IsWindowVisible(hwnd) and _owner(hwnd) == 'order1886-runtime.exe'
                         else None) or True)
    user32.EnumWindows(callback, 0)
    if not found:
        return  # never type into whatever else has focus
    user32.keybd_event(0x12, 0, 0, 0)  # Alt lets SetForegroundWindow take focus from this process
    user32.SetForegroundWindow(found[0])
    user32.keybd_event(0x12, 0, 2, 0)
    if user32.GetForegroundWindow() != found[0]:
        return
    code = {'space': 0x39, 'down': 0x50, 'up': 0x48, 'enter': 0x1C}[key]
    extended = 1 if key in ('down', 'up') else 0
    user32.keybd_event(0, code, 8 | extended, 0)  # KEYEVENTF_SCANCODE
    threading.Event().wait(0.15)
    user32.keybd_event(0, code, 8 | 2 | extended, 0)


def _owner(hwnd):
    import ctypes
    from ctypes import wintypes
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)
    if not handle:
        return ''
    buffer, size = ctypes.create_unicode_buffer(512), wintypes.DWORD(512)
    ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
    ctypes.windll.kernel32.CloseHandle(handle)
    return Path(buffer.value).name.lower()


def to_png(raw):
    """A runtime dump is raw BGRA named <kind>_<index>_<w>x<h>.raw; keep it as an RGB PNG."""
    width, height = map(int, re.search(r'_(\d+)x(\d+)\.raw$', raw.name).groups())
    pixels = np.fromfile(raw, np.uint8).reshape(height, width, 4)[..., [2, 1, 0]]
    png = raw.with_suffix('.png')
    Image.fromarray(pixels).save(png)
    return png


def difference(a, b):
    """Mean absolute pixel difference (0-255) and PSNR; None when the sizes differ."""
    x, y = (np.asarray(Image.open(p), np.float64) for p in (a, b))
    if x.shape != y.shape:
        return None
    mse = float(np.mean((x - y) ** 2))
    return {'mean_abs': float(np.mean(np.abs(x - y))),
            'psnr_db': None if mse == 0 else float(10 * np.log10(255 ** 2 / mse))}


def run(name, args, output):
    folder = output / name
    command = [sys.executable, str(PROBE), '--game-dir', str(args.game_dir),
               '--state-dir', str(output / 'state'), '--output-dir', str(folder),
               '--timeout', str(args.timeout), '--dump-frame', '--frame-rate', str(args.frame_rate),
               '--frame-delay', *map(str, args.delays)]
    if args.cache_seed:
        command += ['--cache-seed', str(args.cache_seed.resolve())]
    if args.runtime:
        command += ['--runtime', str(args.runtime)]
    if name in SHOW_FPS:
        command.append('--show-fps')
    for setting in VARIANTS[name]:
        command += ['--setting', setting]
    shots = output / 'screens' / name
    shots.mkdir(parents=True)
    timers = [threading.Timer(delay, lambda d=delay: ImageGrab.grab().save(shots / f'screen_{d:g}s.png'))
              for delay in args.delays]
    timers += [threading.Timer(float(at), press, (key,)) for at, key in
               (item.split(':') for item in args.keys)]
    process = subprocess.Popen(command, cwd=ROOT)
    for timer in timers:
        timer.start()
    process.wait()
    for timer in timers:
        timer.cancel()
    record = json.loads((folder / 'run.json').read_text(encoding='utf-8'))
    log = (folder / 'native.log').read_text(encoding='utf-8', errors='replace')
    frames = {kind: sorted(to_png(raw) for raw in (folder / 'frames').glob(f'{kind}_*.raw'))
              for kind in ('display', 'output')}
    trace = folder / 'frame-trace-complete.csv'
    text = (folder / 'frame-trace.csv').read_text(encoding='utf-8')
    trace.write_text(text[:text.rfind('\n') + 1], encoding='utf-8', newline='')  # drop the row cut by the timeout
    try:
        timing = perf_report.measure(trace)
    except (perf_report.TraceError, OSError) as error:
        timing = {'error': str(error)}
    return {'settings': VARIANTS[name], 'status': record['status'], 'exit_code': record['exit_code'],
            'settings_line': next((line.strip() for line in log.splitlines() if 'Settings: output' in line), None),
            'frames': {kind: [str(p.relative_to(output)) for p in paths] for kind, paths in frames.items()},
            'screens': sorted(str(p.relative_to(output)) for p in shots.glob('*.png')),
            'timing': timing}


def compare(results, output):
    """Each variant's frames against the baseline's, capture by capture."""
    base = results['baseline']['frames']
    for result in results.values():
        result['vs_baseline'] = {
            kind: [difference(output / a, output / b) for a, b in zip(base[kind], result['frames'][kind])]
            for kind in ('display', 'output')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True, help='new evidence directory')
    parser.add_argument('--delays', type=float, nargs='+', required=True,
                        help='seconds after launch for each frame dump and screenshot')
    parser.add_argument('--timeout', type=float, required=True)
    parser.add_argument('--keys', nargs='*', default=[], metavar='SECONDS:KEY',
                        help='key taps after launch (space, down, up, enter), e.g. 45:space')
    parser.add_argument('--runtime', type=Path, help='runtime to test (default: the built one)')
    parser.add_argument('--frame-rate', type=int, choices=[30, 60], default=60)
    parser.add_argument('--cache-seed', type=Path, help='GPU cache copied into every run (warm start)')
    parser.add_argument('--savedata', type=Path, help='savedata tree copied into the isolated state')
    parser.add_argument('--only', nargs='+', choices=list(VARIANTS), help='run a subset (baseline is always run)')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True)
    if args.savedata:
        shutil.copytree(args.savedata, output / 'state' / 'savedata')
    names = ['baseline', *[n for n in (args.only or VARIANTS) if n != 'baseline']]
    results = {}
    for name in names:
        print(f'== {name}', flush=True)
        results[name] = run(name, args, output)
        (output / 'summary.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    compare(results, output)
    (output / 'summary.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    for name, result in results.items():
        timing = result['timing']
        frame_ms = timing.get('frame_time_ms', {})
        diffs = [d and round(d['mean_abs'], 2) for d in result['vs_baseline']['output']]
        print(f"{name:20} {result['status']:14} fps={timing.get('fps') or 0:6.2f} "
              f"p50={frame_ms.get('p50') or 0:6.2f} p99={frame_ms.get('p99') or 0:7.2f} "
              f"output-diff={diffs}\n    {result['settings_line']}")


if __name__ == '__main__':
    main()
