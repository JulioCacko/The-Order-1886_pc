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
EFFECT_PROBE = ROOT / 'tools' / 'order1886_post_effect_probe.py'
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
    'sync-shaders': ['async_shaders=0'],
    'background-warmup': ['background_warmup=1'],
    'parallel-warmup': ['parallel_warmup=1'],
    'deferred-readbacks': ['speculative_readbacks=1'],
    'fps-cap-45': ['fps_cap=45', 'in_game_menu=1'],
    # Step 10 (#16): each post effect off in a prepared image of its own.
    'motion-blur-off': ['motion_blur=0'],
    'depth-of-field-off': ['depth_of_field=0'],
    'film-grain-off': ['film_grain=0'],
    'chromatic-aberration-off': ['chromatic_aberration=0'],
    'fps-cap-240': ['fps_cap=240'],  # with --frame-rate 0 the cap is the unlocked rate
    'upscaler-fsr3': [],
    'upscaler-dlss': [],
}
SHOW_FPS = {'overlay-none', 'overlay-all'}
# Variants that ask the runtime for a provider in place of the game's temporal resolve (#7).
UPSCALER = {'upscaler-fsr3': 'fsr3', 'upscaler-dlss': 'dlss'}


# Arrows are the right stick (camera) in runtime_pad.c's keyboard map; R is L2 (aim).
SCANCODES = {'space': 0x39, 'down': 0x50, 'up': 0x48, 'left': 0x4B, 'right': 0x4D, 'enter': 0x1C, 'r': 0x13,
             'w': 0x11, 'a': 0x1E, 's': 0x1F, 'd': 0x20}  # WASD is the left stick (walk)
EXTENDED = {'down', 'up', 'left', 'right'}
# Pseudo-keys: a slow relative mouse drag for HOLD seconds (mouse look), 2 px every 10 ms.
MOUSE_MOVES = {'mouse-right': (2, 0), 'mouse-left': (-2, 0)}


def key_tap(text):
    """SECONDS:KEY[:HOLD] for --keys, checked before any run starts; HOLD defaults to a tap."""
    at, _, rest = text.partition(':')
    key, _, hold = rest.partition(':')
    try:
        seconds, held = float(at), float(hold or 0.15)
    except ValueError:
        seconds = held = -1.0
    if not 0 <= seconds < float('inf') or not 0 < held < 60 or key not in (*SCANCODES, *MOUSE_MOVES):
        raise argparse.ArgumentTypeError(
            f'expected SECONDS:KEY[:HOLD] with KEY in {", ".join((*SCANCODES, *MOUSE_MOVES))}: {text!r}')
    return seconds, key, held


def runtime_window(runtime):
    """The visible window of the runtime under test, or None."""
    import ctypes
    user32 = ctypes.windll.user32
    found = []
    callback = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(
        lambda hwnd, _: (found.append(hwnd) if user32.IsWindowVisible(hwnd) and _owner(hwnd) == runtime
                         else None) or True)
    user32.EnumWindows(callback, 0)
    return found[0] if found else None


def window_shot(runtime, path):
    """Save only the game window's client area: the rest of the desktop is never captured."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.SetProcessDPIAware()  # window coordinates in the same physical pixels ImageGrab uses
    window = runtime_window(runtime)
    # Screen pixels, not the window's own: anything drawn over it (Alt+Tab, another app) would be
    # recorded, so capture only while the game window is in front.
    if not window or user32.GetForegroundWindow() != window:
        return
    rect, origin = wintypes.RECT(), wintypes.POINT(0, 0)
    user32.GetClientRect(ctypes.c_void_p(window), ctypes.byref(rect))
    user32.ClientToScreen(ctypes.c_void_p(window), ctypes.byref(origin))
    area = wintypes.RECT(origin.x, origin.y, origin.x + rect.right, origin.y + rect.bottom)
    if area.right <= area.left or area.bottom <= area.top:
        return
    # A topmost window (a notification, an overlay) can cover the game while it stays in front:
    # skip the shot when any visible, uncloaked window above it in z-order overlaps the area.
    user32.GetWindow.restype = ctypes.c_void_p  # a handle; the default c_int truncates it
    above, cloaked, other, overlap = window, wintypes.DWORD(), wintypes.RECT(), wintypes.RECT()
    while above := user32.GetWindow(ctypes.c_void_p(above), 3):  # GW_HWNDPREV
        if not user32.IsWindowVisible(ctypes.c_void_p(above)):
            continue
        ctypes.windll.dwmapi.DwmGetWindowAttribute(ctypes.c_void_p(above), 14, ctypes.byref(cloaked),
                                                   ctypes.sizeof(cloaked))  # DWMWA_CLOAKED
        user32.GetWindowRect(ctypes.c_void_p(above), ctypes.byref(other))
        if not cloaked.value and user32.IntersectRect(ctypes.byref(overlap), ctypes.byref(area),
                                                      ctypes.byref(other)):
            return
    ImageGrab.grab((area.left, area.top, area.right, area.bottom), all_screens=True).save(path)


def press(key, runtime, hold=0.15):
    """Tap a key in the game window (Space is Cross in runtime_pad.c's default map).

    Only a window of the runtime under test counts: another session's runtime may be open.
    """
    import ctypes
    user32 = ctypes.windll.user32
    window = runtime_window(runtime)
    if not window:
        return  # never type into whatever else has focus
    user32.keybd_event(0x12, 0, 0, 0)  # Alt lets SetForegroundWindow take focus from this process
    user32.SetForegroundWindow(window)
    user32.keybd_event(0x12, 0, 2, 0)
    if user32.GetForegroundWindow() != window:
        return
    if key in MOUSE_MOVES:
        dx, dy = MOUSE_MOVES[key]
        for _ in range(max(1, int(hold / 0.01))):
            user32.mouse_event(1, dx, dy, 0, 0)  # MOUSEEVENTF_MOVE, relative
            threading.Event().wait(0.01)
        return
    code = SCANCODES[key]
    extended = 1 if key in EXTENDED else 0
    user32.keybd_event(0, code, 8 | extended, 0)  # KEYEVENTF_SCANCODE
    threading.Event().wait(hold)
    user32.keybd_event(0, code, 8 | 2 | extended, 0)


SAVE_LOADED = "save data 'Playthrough00' mounted"


def continue_save(log, stop, start, runtime, every=4.0, limit=12):
    """Tap Space (Cross) until the runtime mounts the copied playthrough save.

    Boot and menu timing change with the engine rate, so fixed key times can land on the
    wrong menu item and leave the run on the title screen instead of the player's save.
    """
    taps = 0
    if stop.wait(start):
        return taps
    while taps < limit and not stop.is_set():
        if log.is_file() and SAVE_LOADED in log.read_text(encoding='utf-8', errors='replace'):
            break
        press('space', runtime)
        taps += 1
        stop.wait(every)
    return taps


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
    return str(Path(buffer.value)).lower() if buffer.value else ''


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
    if args.frame_capture is not None:
        command += ['--frame-capture', *map(str, args.frame_capture)]
    if args.temporal_probe:
        command.append('--temporal-probe')
    if args.dump_shaders:
        command.append('--dump-shaders')
    if args.cache_seed:
        command += ['--cache-seed', str(args.cache_seed.resolve())]
    if args.runtime:
        command += ['--runtime', str(args.runtime)]
    if name in SHOW_FPS:
        command.append('--show-fps')
    if name in UPSCALER:
        command += ['--upscaler', UPSCALER[name]]
    for setting in [*VARIANTS[name], f'vsync={args.vsync}']:
        command += ['--setting', setting]
    for item in args.env:
        command += ['--env', item]
    shots = output / 'screens' / name
    shots.mkdir(parents=True)
    runtime = str((args.runtime or ROOT / 'out' / 'order1886-runtime.exe').resolve()).lower()
    timers = [threading.Timer(delay, window_shot, (runtime, shots / f'screen_{delay:g}s.png'))
              for delay in args.delays]
    timers += [threading.Timer(at, press, (key, runtime, hold)) for at, key, hold in args.keys]
    samples = output / 'effect-samples' / f'{name}.jsonl'
    if args.sample_effects:
        samples.parent.mkdir(exist_ok=True)
        # Started first: it waits for the runtime and times its reads from the runtime's start.
        reader = subprocess.Popen([sys.executable, str(EFFECT_PROBE), '--output', str(samples), '--runtime', runtime,
                                   '--at', *map(str, args.delays)], cwd=ROOT)
    process = subprocess.Popen(command, cwd=ROOT)
    for timer in timers:
        timer.start()
    stop, taps = threading.Event(), []
    if args.continue_save is not None:
        driver = threading.Thread(target=lambda: taps.append(
            continue_save(folder / 'native.log', stop, args.continue_save, runtime)))
        driver.start()
    process.wait()
    stop.set()
    for timer in timers:
        timer.cancel()
    if args.sample_effects:
        reader.wait()
    if args.continue_save is not None:
        driver.join()
    record = json.loads((folder / 'run.json').read_text(encoding='utf-8'))
    log = (folder / 'native.log').read_text(encoding='utf-8', errors='replace')
    frames = {kind: sorted(to_png(raw) for raw in (folder / 'frames').glob(f'{kind}_*.raw'))
              for kind in ('display', 'output')}
    trace = folder / 'frame-trace-complete.csv'
    raw_trace = folder / 'frame-trace.csv'
    text = raw_trace.read_text(encoding='utf-8') if raw_trace.is_file() else ''
    if '\n' not in text:
        # A runtime that crashed early may leave no trace, or not even a complete header.
        timing = {'error': f'{raw_trace.name}: missing or without a complete line'}
    else:
        header, *rows = text[:text.rfind('\n')].split('\n')  # drop the row cut by the timeout
        if args.measure_after and rows:
            # Keep only the steady scene: rows later than measure_after seconds past the first one.
            start = int(rows[0].split(',')[1]) + int(args.measure_after * 1e9)
            rows = [row for row in rows if int(row.split(',')[1]) >= start]
        trace.write_text('\n'.join([header, *rows]) + '\n', encoding='utf-8', newline='')
        try:
            timing = perf_report.measure(trace)
        except (perf_report.TraceError, OSError) as error:
            timing = {'error': str(error)}
    return {'settings': VARIANTS[name], 'status': record['status'], 'exit_code': record['exit_code'],
            'save_loaded': SAVE_LOADED in log, 'continue_taps': taps[0] if taps else None,
            'settings_line': next((line.strip() for line in log.splitlines() if 'Settings: output' in line), None),
            'frames': {kind: [str(p.relative_to(output)) for p in paths] for kind, paths in frames.items()},
            'screens': sorted(str(p.relative_to(output)) for p in shots.glob('*.png')),
            'timing': timing,
            'effect_samples': ([json.loads(line) for line in samples.read_text(encoding='utf-8').splitlines()]
                               if samples.is_file() else None)}


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
    parser.add_argument('--keys', nargs='*', default=[], metavar='SECONDS:KEY', type=key_tap,
                        help='key presses after launch, e.g. 45:space, held keys such as 84:right:4, '
                             'or mouse look such as 150:mouse-right:6')
    parser.add_argument('--vsync', type=int, choices=[0, 1], default=1,
                        help='0 presents without waiting for the display, so a 60 Hz monitor does not cap the rate')
    parser.add_argument('--continue-save', type=float, metavar='SECONDS',
                        help='from this many seconds after launch, tap Space every 4 s until the copied '
                             "playthrough save is mounted (needs --savedata); replaces fixed menu keys")
    parser.add_argument('--runtime', type=Path, help='runtime to test (default: the built one)')
    parser.add_argument('--frame-rate', type=int, choices=[30, 60, 90, 0], default=60,
                        help='engine rate; 0 is unlocked (paced by fps_cap)')
    parser.add_argument('--frame-capture', type=float, nargs='+', metavar='SECONDS',
                        help='also record one frame census and its pass images (probe --frame-capture)')
    parser.add_argument('--temporal-probe', action='store_true', help='also run the temporal input probe (#7)')
    parser.add_argument('--dump-shaders', action='store_true', help='also dump guest and SPIR-V shaders')
    parser.add_argument('--cache-seed', type=Path, help='GPU cache copied into every run (warm start)')
    parser.add_argument('--measure-after', type=float, default=0,
                        help='frame times count only from this many seconds into the trace')
    parser.add_argument('--savedata', type=Path, help='savedata tree copied into the isolated state')
    parser.add_argument('--sample-effects', action='store_true',
                        help='read the live post-effect strengths at each delay (Windows)')
    parser.add_argument('--env', action='append', default=[], metavar='KEY=VALUE',
                        help='extra runtime environment for every run, e.g. ORDER1886_FRAME_STATS=1')
    parser.add_argument('--only', nargs='+', choices=list(VARIANTS), help='run a subset (baseline is always run)')
    args = parser.parse_args()
    if args.continue_save is not None and not args.savedata:
        parser.error('--continue-save needs --savedata')
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
        print(f"{name:20} {result['status']:14} save={result['save_loaded']} fps={timing.get('fps') or 0:6.2f} "
              f"p50={frame_ms.get('p50') or 0:6.2f} p99={frame_ms.get('p99') or 0:7.2f} "
              f"output-diff={diffs}\n    {result['settings_line']}")


if __name__ == '__main__':
    main()
