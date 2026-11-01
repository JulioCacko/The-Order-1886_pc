"""Button prompts as a launcher option: build the selected set from the player's own dump.

The game's controller glyphs are SWF bitmaps (docs/order1886-ui-assets.md). No game pixel is
shipped: button_prompts/ holds only our own art (letter marks, keycap and mouse drawings) and a
reviewed plan (which bitmap shows which button, and its role per set). At preparation the
selected set is composed from the player's own bitmaps:

- Xbox: the original texture is kept; only the PlayStation marking inside an explicit edit
  region is replaced by the matching letter mark, in the source's own ink, softness and alpha.
  Every pixel outside that region is the source pixel.
- Keyboard and mouse: keycap, mouse and WASD drawings at the original bitmap size and position,
  matching the keyboard-bindings.json layout, which the backend applies with this set.

The result is cached under the state folder per executable, set and art version, and mounted
through the managed overlay after any enabled mods, so the selected prompts win.
"""
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import shutil

ASSETS = Path(__file__).resolve().parent / 'button_prompts'
SETS = ('playstation', 'xbox', 'keyboard')
VERSION = 2  # bump when the composition below changes

XBOX = dict(cross='A', circle='B', square='X', triangle='Y', l1='LB', r1='RB', l2='LT',
            r2='RT', l3='LS', r3='RS', options='MENU', touchpad='VIEW')
# Keycap labels for keyboard-bindings.json. Letters on blank keycaps come from marks/;
# keys with their own drawing (number keys, R, X, Y, ESC) use keyboard/.
KEYS = dict(cross='SPACE', circle='C', square='R', triangle='E', l1='Q', r1='Y', l3='SHIFT',
            r3='X', options='ESC', touchpad='TAB', dpad_up='6', dpad_down='5', dpad_left='2',
            dpad_right='1')
DRAWN_KEYS = {'2': 'number-2', '5': 'number-5', '6': 'number-6', 'R': 'key-R', 'X': 'key-X',
              'Y': 'key-Y', 'ESC': 'key-ESC'}
# Menu discs drawn behind the controller icons: a keycap needs no disc behind it.
MENU_BACKINGS = {114, 276, 277, 285, 288}


def plan(prompt_set):
    """{key: entry} with the reviewed glyph and this set's role. <set>_glyph overrides the
    glyph for one set: a stick printed "L3" is LS on Xbox but still WASD on the keyboard."""
    entries = json.loads((ASSETS / 'plan.json').read_text(encoding='utf-8'))['bitmaps']
    return {e['key']: dict(e, role=e[prompt_set], glyph=e.get(prompt_set + '_glyph', e['glyph']))
            for e in entries}


def keyboard_bindings():
    return json.loads((ASSETS / 'keyboard-bindings.json').read_text(encoding='utf-8'))


# --- shared --------------------------------------------------------------------------------

def _np():
    import numpy
    return numpy


def luminance(rgb):
    """ITU-R 601 luma, as Pillow's L mode."""
    return rgb[..., 0] * .299 + rgb[..., 1] * .587 + rgb[..., 2] * .114


def dilate(mask):
    """3x3 binary dilation of a uint8 mask."""
    from PIL import Image, ImageFilter
    return _np().asarray(Image.fromarray(mask, 'L').filter(ImageFilter.MaxFilter(3)))


def blur(values, sigma):
    from PIL import Image, ImageFilter
    np = _np()
    image = Image.fromarray(np.uint8(np.clip(values * 255, 0, 255)), 'L')
    return np.asarray(image.filter(ImageFilter.GaussianBlur(sigma))).astype(np.float32) / 255


def inpaint(channels, mask):
    """Fill masked pixels from their surroundings, ring by ring, then smooth the fill.

    A small diffusion fill stands in for OpenCV's inpainting: edit regions are a few dozen
    pixels across and the new marking covers most of them."""
    np = _np()
    values = channels.astype(np.float32).copy()
    todo = mask > 0
    if not todo.any():
        return channels.copy()
    known = ~todo
    offsets = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

    def neighbours(array):
        padded = np.pad(array, [(1, 1), (1, 1)] + [(0, 0)] * (array.ndim - 2), mode='edge')
        h, w = array.shape[:2]
        return [padded[1 + dy:1 + dy + h, 1 + dx:1 + dx + w] for dy, dx in offsets]

    while todo.any():
        weight = sum(neighbours(known.astype(np.float32)))
        frontier = todo & (weight > 0)
        if not frontier.any():
            break
        total = sum(n * k[..., None] if values.ndim == 3 else n * k
                    for n, k in zip(neighbours(values), neighbours(known.astype(np.float32))))
        divisor = weight[..., None] if values.ndim == 3 else weight
        values[frontier] = (total / np.maximum(divisor, 1e-6))[frontier]
        known |= frontier
        todo &= ~frontier
    for _ in range(4):
        average = sum(neighbours(values)) / len(offsets)
        values[mask > 0] = average[mask > 0]
    return np.uint8(np.clip(values + .5, 0, 255))


@lru_cache(maxsize=None)
def _mark_image(token):
    from PIL import Image
    path = ASSETS / 'marks' / (token + '.png')
    if not path.is_file():
        raise FileNotFoundError(f'Button prompt art is missing: {path}')
    return Image.open(path).convert('RGBA')


def marking(token, size):
    """The letter silhouette of a mark scaled into size, 0..1. The source decides colour,
    softness and shadow, so the mark's own shading is discarded."""
    from PIL import Image
    np = _np()
    raw = np.asarray(_mark_image(token)).astype(np.float32)
    alpha = raw[..., 3] / 255
    mask = np.clip((luminance(raw[..., :3]) / 255 - .22) / .58, 0, 1) * alpha
    glyph = Image.fromarray(np.uint8(mask * 255), 'L')
    bounds = glyph.point(lambda p: 255 if p > 20 else 0).getbbox()
    if not bounds:
        raise ValueError('Button prompt mark has no visible letter: ' + token)
    glyph = glyph.crop(bounds)
    scale = min(size[0] / glyph.width, size[1] / glyph.height)
    glyph = glyph.resize((max(1, round(glyph.width * scale)), max(1, round(glyph.height * scale))),
                         Image.Resampling.LANCZOS)
    canvas = Image.new('L', size)
    canvas.paste(glyph, ((size[0] - glyph.width) // 2, (size[1] - glyph.height) // 2))
    return np.asarray(canvas).astype(np.float32) / 255


# --- Xbox: replace only the marking ----------------------------------------------------------

def edit_rectangle(e):
    x0, y0, x1, y1 = e['box']
    w, h = x1 - x0, y1 - y0
    if e['glyph'] == 'options':
        return (x0, 7, x1, 22)  # the OPTIONS word; the icon behind it stays
    if e['glyph'] in ('left_stick', 'right_stick') and e['role'] == 'face':
        cy = y0 + h * .32
        return (int(x0 + w * .20), int(cy - h * .19), int(x1 - w * .20), int(cy + h * .19))
    if e['role'] == 'label':
        return (x0, y0, x1, y1)
    if e['static'] and e['glyph'] in ('cross', 'circle', 'square', 'triangle'):
        mx = my = .10
    elif e['glyph'] in ('l1', 'r1', 'l2', 'r2', 'options', 'touchpad'):
        mx, my = .18, .16
    else:
        mx = my = .18
    return (int(x0 + w * mx), int(y0 + h * my), int(x1 - w * mx), int(y1 - h * my))


def composite(e, source, token):
    """The source with its marking replaced by token inside the edit region only."""
    from PIL import Image
    np = _np()
    original = np.asarray(source.convert('RGBA')).copy()
    out = original.copy()
    x0, y0, x1, y1 = edit_rectangle(e)
    native = original[y0:y1, x0:x1]
    allowed = np.zeros(original.shape[:2], np.uint8)
    allowed[y0:y1, x0:x1] = 255
    gx0, gy0, gx1, gy1 = x0, y0, x1, y1
    round_face = e['role'] == 'face' and e['glyph'] not in (
        'l1', 'r1', 'l2', 'r2', 'options', 'touchpad', 'left_stick', 'right_stick')
    if round_face:
        # A rectangle would cut into the ring: edit a concentric disc instead.
        bx0, by0, bx1, by1 = e['box']
        cx, cy = (bx0 + bx1 - 1) / 2, (by0 + by1 - 1) / 2
        r = min(bx1 - bx0, by1 - by0) * .41
        yy, xx = np.indices(allowed.shape)
        allowed = np.uint8(((xx - cx) ** 2 + (yy - cy) ** 2) <= r * r) * 255
        side = int(r * 1.48)
        gx0, gy0 = int(round(cx - side / 2)), int(round(cy - side / 2))
        gx1, gy1 = gx0 + side, gy0 + side
    lum = luminance(native[..., :3].astype(np.float32))
    visible = native[..., 3] > 96
    bright = float(np.mean(lum[visible] > 150)) if visible.any() else 0
    if e['role'] == 'face' and e['glyph'] in ('l1', 'r1', 'l2', 'r2', 'l3', 'r3'):
        bx0, by0, bx1, by1 = e['box']
        bw, bh = bx1 - bx0, by1 - by0
        stick = e['glyph'] in ('l3', 'r3')
        tw, th = int(bw * (.42 if stick else .50)), max(3, int(bh * (.24 if stick else .42)))
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        gx0, gy0 = int(round(cx - tw / 2)), int(round(cy - th / 2))
        gx1, gy1 = gx0 + tw, gy0 + th
    full = np.zeros(original.shape[:2], np.float32)
    gx0, gy0 = max(gx0, 0), max(gy0, 0)
    gx1, gy1 = min(gx1, original.shape[1]), min(gy1, original.shape[0])
    full[gy0:gy1, gx0:gx1] = marking(token, (gx1 - gx0, gy1 - gy0))
    glyph = full[y0:y1, x0:x1]
    if e['soft']:
        glyph = blur(glyph, max(.35, source.width / 128))
    opaque_fraction = float(np.mean(native[..., 3] > 160))
    ink = 'dark' if opaque_fraction > .72 and bright > .58 else 'light'
    white_body = e['role'] == 'face' and e['fill'] > .55 and bright > .67
    if white_body:
        ink = 'dark'
    if e['role'] == 'label':
        ink = 'dark' if visible.any() and float(np.median(lum[visible])) < 80 else 'light'
        out[y0:y1, x0:x1] = 0
        color = 10 if ink == 'dark' else 245
        peak = max(1, int(native[..., 3].max()))
        if ink == 'dark' and bright > .08:
            edge = dilate(np.uint8(glyph * 255)).astype(np.float32) / 255
            rgb = 245 * (1 - glyph[..., None]) + color * glyph[..., None]
            out[y0:y1, x0:x1, :3] = np.uint8(np.clip(rgb, 0, 255))
            out[y0:y1, x0:x1, 3] = np.uint8(np.clip(edge * peak, 0, 255))
        else:
            shifted = np.zeros_like(glyph)
            shifted[1:, 1:] = glyph[:-1, :-1]
            shadow = glyph * .3 + shifted * .7
            alpha = glyph + shadow * (1 - glyph)
            rgb = (color * glyph) / np.maximum(alpha, 1e-6)
            out[y0:y1, x0:x1, :3] = np.uint8(np.clip(rgb[..., None], 0, 255))
            out[y0:y1, x0:x1, 3] = np.uint8(np.clip(alpha * peak, 0, 255))
    else:
        # On a light body the old symbol's grey anti-aliased edges count as ink too, or a
        # ghost triangle or square corners stay around the new letter.
        old_ink = (lum < (200 if white_body else 120)) if ink == 'dark' else (lum > 145)
        if e['glyph'] == 'options':
            old_ink = np.ones(lum.shape, bool)
        old = old_ink & (native[..., 3] > 25)
        if white_body:
            old |= native[..., 3] < 120
        mask = np.zeros(original.shape[:2], np.uint8)
        mask[y0:y1, x0:x1] = np.uint8(old) * 255
        mask = dilate(mask) & allowed
        clean = inpaint(original[..., :3], mask)
        out[mask > 0, :3] = clean[mask > 0]
        opaque = float(np.mean(native[..., 3] > 240)) > .985
        color = 12 if ink == 'dark' else 244
        if opaque or white_body:
            part = out[y0:y1, x0:x1, :3].astype(np.float32)
            out[y0:y1, x0:x1, :3] = np.uint8(part * (1 - glyph[..., None]) + color * glyph[..., None])
            if white_body and not opaque:
                # A light button that cuts its letter out of the alpha: repair the old cut-out,
                # then cut the new letter.
                clean_alpha = inpaint(original[..., 3], mask)
                area = clean_alpha[y0:y1, x0:x1].astype(np.float32)
                out[y0:y1, x0:x1, 3] = np.uint8(area * (1 - glyph))
        else:
            # A mark on a transparent interior: clear the old symbol's opacity in the region.
            alpha = out[y0:y1, x0:x1, 3].astype(np.float32) / 255
            alpha[allowed[y0:y1, x0:x1] > 0] = 0
            rgb = out[y0:y1, x0:x1, :3].astype(np.float32)
            new_a = glyph + alpha * (1 - glyph)
            rgb = (color * glyph[..., None] + rgb * alpha[..., None] * (1 - glyph[..., None])) / \
                np.maximum(new_a[..., None], 1e-6)
            out[y0:y1, x0:x1, :3] = np.uint8(np.clip(rgb, 0, 255))
            out[y0:y1, x0:x1, 3] = np.uint8(np.clip(new_a * 255, 0, 255))
    keep = allowed == 0
    out[keep] = original[keep]  # nothing outside the edit region changes
    return Image.fromarray(out, 'RGBA')


def xbox(entry, image):
    token = XBOX.get(entry['glyph'])
    return composite(entry, image, token) if token else None


# --- keyboard and mouse: drawn keys ----------------------------------------------------------

@lru_cache(maxsize=None)
def master(name):
    from PIL import Image
    image = Image.open(ASSETS / 'keyboard' / (name + '.png')).convert('RGBA')
    grey = image.convert('L')
    image = Image.merge('RGBA', (grey, grey, grey, image.getchannel('A')))
    box = image.getchannel('A').point(lambda v: 255 if v > 20 else 0).getbbox()
    if not box:
        raise ValueError('Empty button prompt drawing: ' + name)
    return image.crop(box)


def keycap(label, size=384):
    from PIL import Image
    np = _np()
    if label in DRAWN_KEYS:
        image = master(DRAWN_KEYS[label]).copy()
        image.thumbnail((size, size), Image.Resampling.LANCZOS)
        return image
    wide = len(label) > 1
    cap = master('key-wide' if wide else 'key-square').copy()
    if wide:  # a compact 2:1 keycap keeps the lettering readable at 32 px
        cap = cap.resize((round(cap.height * 2.1), cap.height), Image.Resampling.LANCZOS)
    cap.thumbnail((size, size), Image.Resampling.LANCZOS)
    tw, th = int(cap.width * (.71 if wide else .54)), int(cap.height * .47)
    letters = marking(label, (tw, th))
    pixels = np.asarray(cap).copy().astype(np.float32)
    x = (cap.width - tw) // 2
    y = max(0, min(int(cap.height * .43) - th // 2, cap.height - th))
    area = pixels[y:y + th, x:x + tw, :3]
    pixels[y:y + th, x:x + tw, :3] = area * (1 - letters[..., None]) + 14 * letters[..., None]
    return Image.fromarray(np.uint8(np.clip(pixels, 0, 255)), 'RGBA')


@lru_cache(maxsize=None)
def drawing(glyph):
    """(image, kind) for a button in the keyboard set."""
    from PIL import Image
    if glyph in ('dpad_up_down', 'dpad_left_right'):
        caps = [keycap(n, 256) for n in (('6', '5') if glyph == 'dpad_up_down' else ('2', '1'))]
        gap = 14
        group = Image.new('RGBA', (sum(c.width for c in caps) + gap, max(c.height for c in caps)))
        x = 0
        for cap in caps:
            group.alpha_composite(cap, (x, (group.height - cap.height) // 2))
            x += cap.width + gap
        return group, 'key-pair'
    if glyph in KEYS:
        return keycap(KEYS[glyph]), 'keycap'
    named = dict(r2='mouse-left', l2='mouse-right', right_stick='mouse-move', left_stick='wasd')
    if glyph in named:
        return master(named[glyph]).copy(), named[glyph]
    raise ValueError('No keyboard or mouse drawing for ' + glyph)


def placed(e, icon, kind):
    """icon at the bitmap's original size, centred where the original drew its button."""
    from PIL import Image, ImageFilter
    width, height = e['width'], e['height']
    bx0, by0, bx1, by1 = e['box']
    bw, bh = bx1 - bx0, by1 - by0
    cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
    if e['role'] == 'label' and max(width, height) < 40:  # the weapon HUD's R1/R2: use it all
        cx, cy, maxw, maxh = width / 2, height / 2, width, height
    elif e['role'] == 'label':
        maxw, maxh = min(width * .72, max(bw * 1.45, 28)), min(height * .64, max(bh * 1.7, 23))
    else:
        maxw, maxh = min(width * .92, bw), min(height * .92, bh)
    if kind == 'keycap' and len(KEYS.get(e['glyph'], '')) > 1:
        maxw = min(width * .90, max(maxw, width * .64))
    if kind.startswith('mouse'):  # a mouse must stay tall, not flatten into a trigger
        maxh = min(height * .86, max(maxh, height * .65))
        maxw = min(width * .82, max(maxw, width * .52))
    if kind == 'wasd':
        maxw = min(width * .92, max(maxw, width * .74))
        maxh = min(height * .84, max(maxh, height * .58))
    if e['glyph'] == 'options':
        cx, cy, maxw, maxh = width / 2, height / 2, width * .80, height * .90
    factor = min(maxw / icon.width, maxh / icon.height)
    icon = icon.resize((max(1, round(icon.width * factor)), max(1, round(icon.height * factor))),
                       Image.Resampling.LANCZOS)
    canvas = Image.new('RGBA', (width, height))
    canvas.alpha_composite(icon, (max(0, min(width - icon.width, round(cx - icon.width / 2))),
                                  max(0, min(height - icon.height, round(cy - icon.height / 2)))))
    if e['soft']:
        canvas = canvas.filter(ImageFilter.GaussianBlur(max(.35, width / 100)))
    return canvas


def keyboard(entry, image):
    # Menus show the keys that act there (Space selects, C goes back): the runtime has no
    # menu-aware mouse routing, so a left-click or Esc prompt would not be true.
    from PIL import Image
    if entry['key'].startswith('MenuApp-') and entry['id'] in MENU_BACKINGS:
        return Image.new('RGBA', image.size)
    icon, kind = drawing(entry['glyph'])
    return placed(entry, icon, kind)


PAINTERS = dict(xbox=xbox, keyboard=keyboard)


# --- cached preparation ----------------------------------------------------------------------

def _fingerprint(game, prompt_set):
    digest = hashlib.sha256(f'{VERSION}:{prompt_set}:'.encode())
    for path in [Path(game) / 'eboot.bin', Path(__file__)] + sorted(p for p in ASSETS.rglob('*') if p.is_file()):
        digest.update(path.name.encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def prepare(game, state, prompt_set, log=print):
    """[(path relative to the game folder, generated file)] for the selected set; empty for the
    game's own PlayStation prompts. Built once per executable, set and art version."""
    if prompt_set not in SETS:
        raise ValueError(f'Button prompts must be one of {", ".join(SETS)}')
    root = Path(state) / 'button-prompts'
    if prompt_set == 'playstation':
        return []
    try:
        import numpy  # noqa: F401
        import PIL  # noqa: F401
        import unicorn  # noqa: F401
    except ImportError as error:
        raise ValueError(f'{prompt_set.capitalize()} button prompts need {error.name}; this '
                         'installation was built without it.') from error
    import order1886_glyph_mod as glyphs
    folder = root / prompt_set
    stamp = folder / 'stamp.json'
    fingerprint = _fingerprint(game, prompt_set)
    try:
        recorded = json.loads(stamp.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        recorded = {}
    built = folder / glyphs.SETS[prompt_set]
    if recorded.get('fingerprint') != fingerprint or not all((built / f).is_file() for f in recorded.get('files', [])):
        log(f'Building {prompt_set} button prompts from your game files (first use only)...')
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
        reviewed = plan(prompt_set)
        resources = sorted({e['resource'] for e in reviewed.values() if e['role'] != 'keep'})
        missing = [r for r in resources if not (Path(game) / glyphs.ui.NAMESPACE / r).is_file()]
        if missing:
            raise ValueError('Button prompts are verified with CUSA00076 1.02; this game has no '
                             f'{missing[0]}. Choose PlayStation prompts.')
        previous, glyphs.RESOURCES = glyphs.RESOURCES, resources
        try:
            _, total = glyphs.build(str(game), prompt_set, str(folder), plan=reviewed,
                                    log=lambda line: None, painter=PAINTERS[prompt_set])
        except SystemExit as error:  # the decoder refuses an unverified executable
            raise ValueError(f'{error} Choose PlayStation prompts.') from None
        finally:
            glyphs.RESOURCES = previous
        files = sorted(p.relative_to(built).as_posix() for p in built.rglob('*') if p.is_file())
        temporary = stamp.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(fingerprint=fingerprint, files=files, bitmaps=total)),
                             encoding='utf-8')
        os.replace(temporary, stamp)
        log(f'{prompt_set.capitalize()} button prompts ready: {total} bitmaps.')
        recorded = dict(files=files)
    return [(Path(f), built / f) for f in recorded['files']]
