"""Drive a running Order runtime to a scene: keys, menu navigation and window shots (Windows).

    python tools/order1886_scene_driver.py RUNTIME OP...

RUNTIME is the runtime executable the window belongs to (another session's runtime is ignored).
Ops run in order:

    key KEY [HOLD]     tap a key (Space = Cross, IJKL = D-pad, arrows = right stick, WASD = left
                       stick, Enter = Options, f12 = RenderDoc capture when its layer is loaded)
    wait SECONDS
    shot PATH          the game window's client area, only while it is in front
    until SECONDS MIN  shoot every few seconds until the frame's mean brightness reaches MIN
    menu               tap Cross on the title until the main menu shows
    chapters           D-pad down until CHAPTERS is highlighted, then Cross
    gate               create the file named by $GATE (marks "past the menus" for diagnostics)

Chapter II "Evidence" (Council close-ups, face shading) from a playthrough save:

    ... wait 25 until 120 25 wait 2 menu chapters wait 4 key l 0.3 wait 1.5 key l 0.3 wait 2 \
        key space 0.5 wait 5 until 150 15 shot a.png

Pitfalls this handles: a bare Alt tap (used to take focus) puts the window in menu mode and
eats the next key, so Alt is sent only when the window is not already in front and Esc follows
it; the title ignores Cross until its animation ends, so `menu` retries and checks the menu text.
"""
import ctypes
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import order1886_step1_evidence as ev  # noqa: E402
from PIL import Image, ImageStat  # noqa: E402

user32 = ctypes.windll.user32
ev.SCANCODES.update(i=0x17, j=0x24, k=0x25, l=0x26, q=0x10, e=0x12, c=0x2E, z=0x2C, f=0x21,
                    f12=0x58)
POLL = os.path.join(tempfile.gettempdir(), 'order1886-scene-driver-poll.png')


def focus(runtime):
    window = ev.runtime_window(runtime)
    if window and user32.GetForegroundWindow() != window:
        user32.keybd_event(0x12, 0, 0, 0)
        user32.SetForegroundWindow(window)
        user32.keybd_event(0x12, 0, 2, 0)
        time.sleep(0.3)
        user32.keybd_event(0x1B, 0, 0, 0)  # leave the menu mode the Alt tap may have entered
        user32.keybd_event(0x1B, 0, 2, 0)
        time.sleep(0.2)
    return window


def press(key, runtime, hold):
    window = focus(runtime)
    if not window or user32.GetForegroundWindow() != window:
        return
    if key in ev.MOUSE_MOVES:
        dx, dy = ev.MOUSE_MOVES[key]
        for _ in range(max(1, int(hold / 0.01))):
            user32.mouse_event(1, dx, dy, 0, 0)
            time.sleep(0.01)
        return
    code, extended = ev.SCANCODES[key], 1 if key in ev.EXTENDED else 0
    user32.keybd_event(0, code, 8 | extended, 0)
    time.sleep(hold)
    user32.keybd_event(0, code, 8 | 2 | extended, 0)


def grab(runtime):
    focus(runtime)
    ev.window_shot(runtime, POLL)
    try:
        return Image.open(POLL).convert('L')
    except OSError:
        return None


def region(image, box):
    return ImageStat.Stat(image.crop(box)).mean[0] if image else -1


def main(argv):
    runtime = argv[0].lower()
    args = argv[1:]
    while args:
        op = args.pop(0)
        if op == 'key':
            key = args.pop(0)
            hold = float(args.pop(0)) if args and args[0].replace('.', '').isdigit() else 0.15
            press(key, runtime, hold)
            time.sleep(0.6)
        elif op == 'wait':
            time.sleep(float(args.pop(0)))
        elif op == 'shot':
            focus(runtime)
            ev.window_shot(runtime, args.pop(0))
        elif op == 'gate':
            if os.environ.get('GATE'):
                Path(os.environ['GATE']).touch()
        elif op == 'until':
            limit, low = float(args.pop(0)), float(args.pop(0))
            end = time.time() + limit
            while time.time() < end:
                image = grab(runtime)
                mean = ImageStat.Stat(image).mean[0] if image else -1
                print(f'{limit - (end - time.time()):.0f}s mean={mean:.1f}', flush=True)
                if mean >= low:
                    break
                time.sleep(3)
        elif op == 'menu':
            for _ in range(8):
                press('space', runtime, 0.5)
                time.sleep(4)
                mean = region(grab(runtime), (320, 390, 520, 470))
                print(f'menu text mean={mean:.1f}', flush=True)
                if mean > 55:
                    break
        elif op == 'chapters':
            for _ in range(8):
                press('k', runtime, 0.4)
                time.sleep(1.5)
                image = grab(runtime)
                rows = [region(image, (300, y, 700, y + 24)) for y in (398, 438)]
                print(f'rows continue={rows[0]:.1f} chapters={rows[1]:.1f}', flush=True)
                if rows[1] > rows[0]:
                    press('space', runtime, 0.5)
                    break
                if rows[0] < 20:
                    break
        else:
            raise SystemExit(f'unknown op {op!r}')


if __name__ == '__main__':
    main(sys.argv[1:])
