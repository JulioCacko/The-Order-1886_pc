"""Build Xbox or keyboard-and-mouse button prompt mods from the player's own dump.

    python tools/order1886_glyph_mod.py pack GAME_DIR --output PACK
    python tools/order1886_glyph_mod.py build GAME_DIR --set xbox|keyboard --mods MODS
                                        [--plan PACK/plan.json] [--art PACK/art]
                                        [--keyboard-bindings JSON]

`pack` writes an art request pack (docs/order1886-glyph-art-guide.md): every glyph bitmap as
PNG under sources/, contact-sheet.png, plan.json (editable glyph and role per bitmap) and
GPT-PROMPTS.md (what to generate, with prompts and return file names). `build` replaces each
planned bitmap with, in order: PACK/art/<set>/bitmaps/<key>.png (an exact redraw of that
source), PACK/art/<set>/<glyph>.png or <glyph>_label.png, or art drawn here; then it writes
MODS/"Glyphs - Xbox" (or "... Keyboard and mouse") for Advanced > Mods. No game asset is
stored in the repository; PACK and MODS must be outside it and outside GAME_DIR.

Pillow 10.1 or newer draws the labels. Replacements keep every character id and bitmap size. Movies inside packages must fit their
slot, and packages stay COMPRESS: changed 256 KiB chunks are stored uncompressed, the rest
keep their original Oodle data (docs/order1886-ui-assets.md).
"""
import argparse
import json
import math
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import order1886_ui_extract as ui  # noqa: E402

SETS = {'xbox': 'Glyphs - Xbox', 'keyboard': 'Glyphs - Keyboard and mouse'}
# Resources with glyph bitmaps (1.02): standalone menu, shared UI package, two Lycan levels.
RESOURCES = ['primary/c2d79afbc68fc86c/v1/e32dc7d7dc8151e2'] + [
    'primary/3861c21fc34b7612/v11345526222/' + name
    for name in ('baceeaafdf99323d', 'ec5e1979c41e637c', 'd107aa37d606b0be')]
TOKENS = ['cross', 'circle', 'square', 'triangle', 'l1', 'r1', 'l2', 'r2', 'l3', 'r3',
          'left_stick', 'right_stick', 'left_stick_forward', 'left_stick_back',
          'dpad_up', 'dpad_down', 'dpad_left', 'dpad_right', 'dpad_up_down', 'dpad_left_right',
          'touchpad', 'options', 'cross_circle_swap']
PLAYSTATION = {'cross': 'Cross (X)', 'circle': 'Circle (O)', 'square': 'Square', 'triangle': 'Triangle',
               'l1': 'L1', 'r1': 'R1', 'l2': 'L2', 'r2': 'R2', 'l3': 'L3', 'r3': 'R3',
               'left_stick': 'L stick', 'right_stick': 'R stick', 'left_stick_forward': 'L stick up',
               'left_stick_back': 'L stick down', 'dpad_up': 'D-pad up', 'dpad_down': 'D-pad down',
               'dpad_left': 'D-pad left', 'dpad_right': 'D-pad right', 'dpad_up_down': 'D-pad up/down',
               'dpad_left_right': 'D-pad left/right', 'touchpad': 'Touchpad', 'options': 'OPTIONS',
               'cross_circle_swap': 'Cross/Circle'}
XBOX = {'cross': 'A', 'circle': 'B', 'square': 'X', 'triangle': 'Y', 'l1': 'LB', 'r1': 'RB',
        'l2': 'LT', 'r2': 'RT', 'l3': 'LS', 'r3': 'RS', 'left_stick': 'L', 'right_stick': 'R',
        'left_stick_forward': 'L', 'left_stick_back': 'L', 'dpad_up': '', 'dpad_down': '',
        'dpad_left': '', 'dpad_right': '', 'dpad_up_down': '', 'dpad_left_right': '',
        'options': 'MENU', 'touchpad': 'VIEW', 'cross_circle_swap': 'A'}
# Runtime keyboard defaults (src/runtime_pad.c key_map); mouse supplies R2 (left) and L2 (right).
KEYBOARD = {'cross': 'Space', 'circle': 'Left Shift', 'square': 'E', 'triangle': 'Q', 'l1': '1',
            'r1': '3', 'l3': 'Z', 'r3': 'C', 'options': 'Return', 'touchpad_left': 'Tab',
            'up': 'I', 'down': 'K', 'left': 'J', 'right': 'L'}
KEY_LABELS = {'Left Shift': 'SHIFT', 'Right Shift': 'SHIFT', 'Return': 'ENTER', 'Space': 'SPACE',
              'Backspace': 'BKSP', 'Left Ctrl': 'CTRL', 'Right Ctrl': 'CTRL', 'Left Alt': 'ALT',
              'Right Alt': 'ALT', 'Escape': 'ESC', 'Tab': 'TAB', '__unbound__': '-'}


# --- plan ---------------------------------------------------------------------------------

def analyse(image):
    """Opaque box, fill, polarity, softness and label detail of one bitmap, measured inside
    its own box so a small icon on a large canvas compares like a big one."""
    from PIL import ImageChops, ImageFilter, ImageStat
    alpha = image.getchannel('A')
    box = alpha.point(lambda v: 255 if v > 32 else 0).getbbox()
    if not box:
        return dict(box=None, area=0, fill=0, detail=0, dark=0, inverted=False, soft=False, flat=True)
    glyph = image.crop(box)
    w, h = glyph.size
    lum, solid = glyph.convert('L'), glyph.getchannel('A').point(lambda v: 255 if v > 200 else 0)
    stat = ImageStat.Stat(lum, solid)
    fill = stat.count[0] / (w * h)
    centre = (int(w * .25), int(h * .25), int(w * .75), int(h * .75))
    c_lum, c_mask = lum.crop(centre), solid.crop(centre)
    detail = 0.0
    if ImageStat.Stat(c_lum, c_mask).count[0]:
        blurred = c_lum.filter(ImageFilter.GaussianBlur(max(1, w / 32)))
        detail = ImageStat.Stat(ImageChops.difference(c_lum, blurred), c_mask).mean[0]
    dark_mask = ImageChops.multiply(lum.point(lambda v: 255 if v < 90 else 0), solid)
    dark = ImageStat.Stat(dark_mask).mean[0] / 255 / max(fill, 1e-6)
    mean = stat.mean[0] if stat.count[0] else 0
    return dict(box=list(box), area=round(w * h / (image.width * image.height), 2),
                fill=round(fill, 2), detail=round(detail, 1), dark=round(dark, 2),
                inverted=bool(stat.count[0] and mean < 110), soft=bool(detail < 20 and dark < 0.05),
                flat=bool(not stat.count[0] or stat.stddev[0] < 3 or dark > 0.9))


MARKS = ('cross', 'circle', 'square', 'triangle')


def suggest_role(info, static, glyph):
    """face: a whole button icon; label: the button's text or mark drawn over a blank body;
    keep: rings, wipes, masks, fail splats, blank bodies and glows. A heuristic: review the
    contact sheet and edit plan.json (the guide shows each role)."""
    if static and not info['flat']:  # the only bitmap of a ButtonIcon symbol is the icon itself
        return 'face'
    if glyph in MARKS and info['box'] and 0.15 <= info['area'] <= 0.55 and info['fill'] < 0.45:
        return 'label'  # an X, O, square or triangle drawn alone (white, or black when inverted)
    if info['flat']:
        return 'keep'
    if info['area'] <= 0.16 and info['detail'] >= 30:
        return 'label'
    if info['fill'] >= 0.15 and info['detail'] >= 30 and info['dark'] >= 0.15:
        return 'face'
    return 'keep'


def owner_glyph(owners, movie, symbols):
    """The glyph most owning buttons agree on, then the most specific owner (fewest bitmaps).
    Overlays are shared between buttons, so plan.json lets a reviewer correct it."""
    votes = {}
    for name, cid in symbols:
        glyph = ui.glyph_of([name])
        if glyph and name in owners:
            count, size = votes.get(glyph, (0, 1 << 30))
            votes[glyph] = (count + 1, min(size, len(ui.bitmaps_under(movie, cid))))
    return min(votes, key=lambda g: (-votes[g][0], votes[g][1])) if votes else None


def glyph_bitmaps(game, oodle):
    """(resource, blob, payload, [(offset, movie, [(key, id, glyph, static, image, info)])])"""
    root = Path(game) / ui.NAMESPACE
    for name in RESOURCES:
        blob = (root / name).read_bytes()
        data, _ = ui.payload(blob, oodle)
        found = []
        for offset in ui.find_swfs(data):
            movie = ui.parse_swf(data[offset:])
            names = {**movie['exports'], **movie['symbols']}
            symbols = [(n, c) for c, n in names.items()]
            owners = {}
            for cid, symbol in names.items():
                for b in ui.bitmaps_under(movie, cid):
                    owners.setdefault(b, []).append(symbol)
            app = next((n[9:] for n in names.values() if n.startswith('rad.apps.')), 'Movie')
            items = []
            for cid, bitmap in sorted(movie['bitmaps'].items()):
                glyph = owner_glyph(owners.get(cid, []), movie, symbols)
                if not glyph:
                    continue
                static = any('ButtonIcon' in n and n in owners.get(cid, []) and
                             len(ui.bitmaps_under(movie, c)) == 1 for n, c in symbols)
                image = ui.decode_bitmap(bitmap)
                items.append((f'{app}-{offset:x}-{cid}', cid, glyph, static, image, analyse(image)))
            found.append((offset, movie, items))
        yield name, blob, data, found


def labels_for(set_name, bindings=None):
    """The text each glyph token shows in a set."""
    if set_name == 'xbox':
        return dict(XBOX)
    keys = dict(KEYBOARD, **(bindings or {}))
    def key(button):
        name = keys.get(button, '')
        return KEY_LABELS.get(name, name.upper() if len(name) <= 5 else name[:5].upper())
    out = {t: key(t) for t in ('cross', 'circle', 'square', 'triangle', 'l1', 'r1', 'l3', 'r3', 'options')}
    out.update(touchpad=key('touchpad_left'), l2='RMB', r2='LMB', left_stick='WASD', right_stick='MOUSE',
               left_stick_forward='W', left_stick_back='S', dpad_up=key('up'), dpad_down=key('down'),
               dpad_left=key('left'), dpad_right=key('right'), dpad_up_down=key('up') + '/' + key('down'),
               dpad_left_right=key('left') + '/' + key('right'), cross_circle_swap=key('cross'))
    return out


def pack(game, output):
    from PIL import Image, ImageDraw
    oodle = ui.Oodle(str(Path(game) / 'eboot.bin'))
    entries, thumbs = [], []
    for name, _, _, found in glyph_bitmaps(game, oodle):
        for offset, _, items in found:
            for key, cid, glyph, static, image, info in items:
                source = Path('sources') / f'{key}.png'
                (output / source).parent.mkdir(parents=True, exist_ok=True)
                image.save(output / source)
                entries.append(dict(key=key, glyph=glyph, role=suggest_role(info, static, glyph),
                                    resource=name, offset=offset, id=cid, width=image.width,
                                    height=image.height, source=source.as_posix(), static=static, **info))
                thumbs.append(image)
    # 1:1 references for redrawing by hand or with an image model: same framing, enlarged to
    # 512 px on the longest side, on the dark grey the game draws prompts over.
    for entry, image in zip(entries, thumbs):
        if entry['role'] == 'keep':
            continue
        scale = 512 / max(image.size)
        big = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
        reference = Image.new('RGBA', big.size, (42, 42, 42, 255))
        reference.alpha_composite(big)
        path = output / 'reference' / f'{entry["key"]}.png'
        path.parent.mkdir(parents=True, exist_ok=True)
        reference.convert('RGB').save(path)
    (output / 'plan.json').write_text(json.dumps(dict(
        note='Edit "glyph" (one of: ' + ', '.join(TOKENS) + ') and "role" (face, label or keep) '
             'per bitmap; build follows this file.', bitmaps=entries), indent=1))
    size, cols = 104, 12
    colours = {'face': (60, 200, 90, 255), 'label': (70, 150, 255, 255), 'keep': (100, 100, 100, 255)}
    sheet = Image.new('RGBA', (cols * size, math.ceil(len(entries) / cols) * (size + 28)), (55, 55, 55, 255))
    draw = ImageDraw.Draw(sheet)
    for i, (entry, image) in enumerate(zip(entries, thumbs)):
        x, y = (i % cols) * size, (i // cols) * (size + 28)
        thumb = image.copy()
        thumb.thumbnail((size - 12, size - 12))
        draw.rectangle((x + 1, y + 1, x + size - 2, y + size - 2), outline=colours[entry['role']], width=3)
        sheet.alpha_composite(thumb, (x + 6, y + 6))
        draw.text((x + 3, y + size), entry['key'].replace('App-', ' ')[:17], fill=(255, 230, 0, 255))
        draw.text((x + 3, y + size + 12), f"{entry['role']} {entry['glyph']}"[:17], fill=(140, 220, 255, 255))
    sheet.save(output / 'contact-sheet.png')
    (output / 'GPT-PROMPTS.md').write_text(prompts(entries), encoding='utf-8')
    return entries


def prompts(entries):
    xbox, keyboard = labels_for('xbox'), labels_for('keyboard')
    used = [e for e in entries if e['role'] != 'keep']
    lines = [
        '# Glyph art requests', '',
        'Read docs/order1886-glyph-art-guide.md first. Save every image you get back under',
        '`art/` in this folder with the exact name given, then run `build --art <this folder>/art`.',
        'Anything you do not provide is drawn by the tool, so you can start small.', '',
        '## Route A: one image per button (quick)', '',
        'For each row, attach one or two of the listed sources as the style reference and use the',
        'face or label prompt from the guide with the target text.', '',
        '| Button | Xbox | Keyboard (defaults) | Return files | Style references |', '|---|---|---|---|---|']
    for token in TOKENS:
        mine = [e for e in used if e['glyph'] == token]
        if not mine:
            continue
        roles = sorted({e['role'] for e in mine})
        files = ', '.join(f'`{s}/{token}{"" if r == "face" else "_label"}.png`'
                          for s in ('xbox', 'keyboard') for r in roles)
        refs = ', '.join(f'`{e["source"]}`' for e in mine[:2])
        lines.append(f'| {PLAYSTATION[token]} | {xbox[token] or "D-pad"} | {keyboard[token]} | {files} | {refs} |')
    lines += [
        '', '## Route B: redraw each source exactly (best match)', '',
        'Start from `reference/<key>.png` (the source enlarged 1:1 on dark grey) and change only the',
        'PlayStation marking (prompt B in the guide). Keep the framing and aspect ratio and give the',
        'result a transparent background. Save it as `art/<set>/bitmaps/<key>.png`: build scales it',
        'back to the source size exactly.', '',
        '| Key | Reference | Size | Role | Shows | Xbox | Keyboard |', '|---|---|---|---|---|---|---|']
    for e in used:
        lines.append(f'| `{e["key"]}` | `reference/{e["key"]}.png` | {e["width"]}x{e["height"]} | {e["role"]} | '
                     f'{PLAYSTATION[e["glyph"]]} | {xbox[e["glyph"]] or "D-pad"} | {keyboard[e["glyph"]]} |')
    return '\n'.join(lines) + '\n'


# --- art ----------------------------------------------------------------------------------

BODY, INK, EDGE = (236, 236, 236, 255), (20, 20, 20, 255), (40, 40, 40, 255)


def font(size):
    from PIL import ImageFont
    return ImageFont.load_default(size=max(8, int(size)))


def fit_text(draw, label, width, height, stroke):
    """The largest font that keeps the label inside width x height."""
    size = int(height)
    while size > 8:
        left, top, right, bottom = draw.textbbox((0, 0), label, font=font(size), stroke_width=stroke)
        if right - left <= width and bottom - top <= height:
            break
        size = int(size * 0.92)
    return font(size)


def draw_label(label, size=256):
    """A label or mark alone: off-white serif-like capitals with a dark outline, as the
    game's overlays are drawn."""
    from PIL import Image, ImageDraw
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    if label:
        d, stroke = ImageDraw.Draw(image), max(2, size // 40)
        d.text((size / 2, size / 2), label, fill=BODY, anchor='mm', stroke_width=stroke, stroke_fill=INK,
               font=fit_text(d, label, size * .9, size * .6, stroke))
    return image


def draw_face(token, set_name, label, size=256):
    """A whole button icon: off-white body, dark outline, dark label (the game's palette)."""
    from PIL import Image, ImageDraw
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    s, m = size, size // 16
    w = max(2, m // 2)
    if set_name == 'keyboard' and token in ('l2', 'r2'):  # mouse with the button filled
        d.rounded_rectangle((s * .28, m, s * .72, s - m), radius=s * .22, fill=BODY, outline=EDGE, width=w)
        d.line((s * .5, m, s * .5, s * .42), fill=EDGE, width=w)
        d.line((s * .28, s * .42, s * .72, s * .42), fill=EDGE, width=w)
        x0, x1 = (s * .3, s * .5) if token == 'r2' else (s * .5, s * .7)
        d.rectangle((x0 + w, m * 2, x1 - w, s * .42 - w), fill=INK)
        return image
    if set_name == 'xbox' and token.startswith('dpad'):
        arm = s * .34
        d.rectangle((arm, m, s - arm, s - m), fill=BODY, outline=EDGE, width=w)
        d.rectangle((m, arm, s - m, s - arm), fill=BODY, outline=EDGE, width=w)
        lit = {'up': [(arm, m, s - arm, arm)], 'down': [(arm, s - arm, s - arm, s - m)],
               'left': [(m, arm, arm, s - arm)], 'right': [(s - arm, arm, s - m, s - arm)]}
        lit['up_down'], lit['left_right'] = lit['up'] + lit['down'], lit['left'] + lit['right']
        for box in lit[token[5:]]:
            d.rectangle(box, fill=INK)
        return image
    if set_name == 'keyboard':
        box = (m, s * .24, s - m, s * .76) if len(label) > 2 else (m * 2, m * 2, s - m * 2, s - m * 2)
        d.rounded_rectangle(box, radius=s // 10, fill=BODY, outline=EDGE, width=w)
    elif token in ('l1', 'r1'):
        d.rounded_rectangle((m, s * .3, s - m, s * .7), radius=s // 8, fill=BODY, outline=EDGE, width=w)
    elif token in ('l2', 'r2'):
        d.polygon([(s * .22, s * .14), (s * .78, s * .14), (s - m, s * .86), (m, s * .86)],
                  fill=BODY, outline=EDGE, width=w)
    else:
        d.ellipse((m, m, s - m, s - m), fill=BODY, outline=EDGE, width=w)
        if token in ('left_stick_forward', 'left_stick_back'):
            up = token.endswith('forward')
            tip, base = (m * 1.5, m * 3.5) if up else (s - m * 1.5, s - m * 3.5)
            d.polygon([(s / 2, tip), (s / 2 - m * 1.5, base), (s / 2 + m * 1.5, base)], fill=INK)
    if label:
        wide = len(label) > 2 if set_name == 'keyboard' else token in ('l1', 'r1')
        stroke = max(1, s // 96)
        d.text((s / 2, s / 2), label, fill=INK, anchor='mm', stroke_width=stroke, stroke_fill=INK,
               font=fit_text(d, label, s * (.78 if wide else .56), s * (.32 if wide else .5), stroke))
    return image


def fitted(art, original, info, role='face'):
    """Art scaled into the original's opaque box, in its softness. Faces keep the art's own
    tones (the game's "Invert" icons are still light bodies); a dark mark gets the label's
    bright strokes in dark ink, so a halo around the letters does not turn into a box."""
    from PIL import Image, ImageFilter
    out = Image.new('RGBA', original.size, (0, 0, 0, 0))
    x0, y0, x1, y1 = info['box']
    art = art.convert('RGBA')
    art = art.crop(art.getchannel('A').getbbox() or (0, 0, art.width, art.height))
    scale = min((x1 - x0) / art.width, (y1 - y0) / art.height)
    art = art.resize((max(1, round(art.width * scale)), max(1, round(art.height * scale))), Image.LANCZOS)
    if role == 'label' and info['inverted']:
        strokes = Image.composite(art.convert('L'), Image.new('L', art.size), art.getchannel('A'))
        art = Image.merge('RGBA', (*Image.new('RGB', art.size, INK[:3]).split(), strokes))
    out.alpha_composite(art, ((x0 + x1 - art.width) // 2, (y0 + y1 - art.height) // 2))
    if info['soft']:
        out = out.filter(ImageFilter.GaussianBlur(max(1, original.width / 24)))
    return out


def replacement(entry, original, set_name, labels, art):
    """The new image for one planned bitmap: exact redraw, per-glyph art, or drawn here."""
    from PIL import Image
    if art:
        exact = Path(art) / set_name / 'bitmaps' / f'{entry["key"]}.png'
        if exact.is_file():
            return Image.open(exact).convert('RGBA').resize(original.size, Image.LANCZOS)
        generic = Path(art) / set_name / f'{entry["glyph"]}{"" if entry["role"] == "face" else "_label"}.png'
        if generic.is_file():
            return fitted(Image.open(generic), original, entry, entry['role'])
    label = labels[entry['glyph']]
    drawn = draw_face(entry['glyph'], set_name, label) if entry['role'] == 'face' else draw_label(label)
    return fitted(drawn, original, entry, entry['role'])


def lossless2(cid, image):
    """DefineBitsLossless2 payload: 8-bit palette (format 3) or premultiplied ARGB (format 5),
    whichever is smaller. Monochrome prompt art fits a palette without visible loss, and
    package slots are tight."""
    from PIL import Image
    image = image.convert('RGBA')
    rgba = image.tobytes()
    pixels = bytearray(len(rgba))
    for i in range(0, len(rgba), 4):
        r, g, b, a = rgba[i:i + 4]
        pixels[i:i + 4] = bytes((a, r * a // 255, g * a // 255, b * a // 255))
    best = struct.pack('<HBHH', cid, 5, image.width, image.height) + zlib.compress(bytes(pixels), 9)
    indexed = image.quantize(256, method=Image.Quantize.FASTOCTREE)
    count = len(indexed.getpalette(rawmode='RGBA')) // 4
    table = bytearray()
    for r, g, b, a in zip(*[iter(indexed.getpalette(rawmode='RGBA'))] * 4):
        table += bytes((r * a // 255, g * a // 255, b * a // 255, a))  # premultiplied RGBA
    stride = (image.width + 3) & ~3
    rows = indexed.tobytes()
    data = b''.join(rows[y * image.width:(y + 1) * image.width].ljust(stride, b'\x00')
                    for y in range(image.height))
    palette = struct.pack('<HBHHB', cid, 3, image.width, image.height, count - 1) +         zlib.compress(bytes(table) + data, 9)
    if len(palette) >= len(best):
        return best
    # Quantising RGBA can fold transparent pixels into an opaque colour: keep the palette only
    # when its alpha still matches the art.
    decoded = ui.decode_bitmap(dict(tag='DefineBitsLossless2', data=palette, format=3,
                                    width=image.width, height=image.height))
    drift = max(abs(a - b) for a, b in zip(decoded.getchannel('A').tobytes(), image.getchannel('A').tobytes()))
    return palette if drift <= 48 else best


# --- SWF and container rebuild ------------------------------------------------------------

def tag_bytes(code, data):
    if len(data) < 63 and code not in ui.TAG_NAMES:
        return struct.pack('<H', code << 6 | len(data)) + data
    return struct.pack('<HI', code << 6 | 63, len(data)) + data


def rebuild_swf(swf, replacements):
    """The movie with bitmap tags replaced ({id: DefineBitsLossless2 payload}), as CWS."""
    body = ui.swf_body(swf)
    _, pos = ui.read_rect(body, 0)
    out = bytearray(body[:pos + 4])
    for code, data in ui.tags(body, pos + 4):
        cid = struct.unpack_from('<H', data)[0] if code in ui.TAG_NAMES and len(data) >= 2 else None
        if cid in replacements:
            code, data = 36, replacements[cid]
        out += tag_bytes(code, data)
    return b'CWS' + swf[3:4] + struct.pack('<I', len(out) + 8) + zlib.compress(bytes(out), 9)


def place(payload, offset, swf):
    """The payload with a movie rewritten in its slot (u32 size before it, zero padding)."""
    if offset == 4 and struct.unpack_from('<I', payload)[0] == len(payload) - 4:
        return struct.pack('<I', len(swf)) + swf  # a resource holding only this movie may grow
    slot = struct.unpack_from('<I', payload, offset - 4)[0]
    if len(swf) > slot:
        raise ValueError(f'movie at {offset:#x} needs {len(swf)} bytes, its slot holds {slot}: '
                         'use simpler art (flat colours compress best)')
    return payload[:offset] + swf + bytes(slot - len(swf)) + payload[offset + slot:]


def repack(blob, original, payload):
    """Same container kind: raw stays raw; chunked COMPRESS keeps unchanged chunks' Oodle data
    and stores changed ones uncompressed (header byte 0, decoded by the game's own Oodle)."""
    if blob[:8] != b'COMPRESS':
        return payload
    raw, chunks = ui.container_chunks(blob)
    if len(chunks) == 1:
        return payload  # standalone single-stream resources load raw (verified in game)
    if len(payload) != raw:
        raise ValueError('a package payload must keep its size')
    body = bytearray()
    for p, n, offset, size in chunks:
        part = payload[offset:offset + size]
        chunk = blob[p:p + n] if part == original[offset:offset + size] else bytes(1) + part
        body += struct.pack('<QQ', offset, len(chunk)) + chunk
    return b'COMPRESS' + struct.pack('<QQ', raw, 24 + len(body)) + bytes(body)


def build(game, set_name, mods, plan=None, art=None, bindings=None, log=print):
    oodle = ui.Oodle(str(Path(game) / 'eboot.bin'))
    labels = labels_for(set_name, bindings)
    planned = {e['key']: e for e in json.loads(Path(plan).read_text())['bitmaps']} if plan else {}
    folder = Path(mods) / SETS[set_name]
    total = 0
    for name, blob, data, found in glyph_bitmaps(game, oodle):
        payload = data
        for offset, movie, items in sorted(found, key=lambda f: -f[0]):
            replacements = {}
            for key, cid, glyph, static, image, info in items:
                entry = dict(info, key=key, glyph=glyph, role=suggest_role(info, static, glyph))
                entry.update({k: planned[key][k] for k in ('glyph', 'role') if key in planned})
                if entry['role'] not in ('face', 'label', 'keep') or (
                        entry['role'] != 'keep' and entry['glyph'] not in TOKENS):
                    raise SystemExit(f'plan.json: {key} has glyph {entry["glyph"]!r} and role '
                                     f'{entry["role"]!r}; use a glyph from the list and face, label or keep')
                if set_name == 'xbox' and entry['glyph'].startswith('dpad'):
                    continue  # the PS4 and Xbox D-pads are the same: keep the game's own art
                if entry['role'] in ('face', 'label') and info['box']:
                    replacements[cid] = lossless2(cid, replacement(entry, image, set_name, labels, art))
            if replacements:
                payload = place(payload, offset, rebuild_swf(payload[offset:], replacements))
                total += len(replacements)
                log(f'{name} @{offset:#x}: {len(replacements)} bitmaps')
        if payload is not data:
            target = folder / ui.NAMESPACE / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(repack(blob, data, payload))
    return folder, total


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('pack')
    p.add_argument('game_dir', type=Path)
    p.add_argument('--output', type=Path, required=True)
    b = sub.add_parser('build')
    b.add_argument('game_dir', type=Path)
    b.add_argument('--set', choices=sorted(SETS), required=True)
    b.add_argument('--mods', type=Path, required=True, help='the mods folder chosen in Advanced')
    b.add_argument('--plan', type=Path, help='plan.json from pack (default: the built-in suggestions)')
    b.add_argument('--art', type=Path, help='folder holding <set>/<glyph>.png and <set>/bitmaps/<key>.png')
    b.add_argument('--keyboard-bindings', default='{}', help='the launcher/CLI keyboard bindings JSON')
    args = parser.parse_args(argv)
    game = args.game_dir
    if not (game / 'eboot.bin').is_file():
        raise SystemExit(f'{game} does not hold eboot.bin')
    if args.command == 'pack':
        output = ui.check_output(args.output, game)
        output.mkdir(parents=True, exist_ok=True)
        entries = pack(game, output)
        roles = {r: sum(e['role'] == r for e in entries) for r in ('face', 'label', 'keep')}
        print(f'{len(entries)} glyph bitmaps ({roles}) -> {output}')
    else:
        mods = ui.check_output(args.mods, game)
        folder, total = build(game, args.set, mods, args.plan, args.art, json.loads(args.keyboard_bindings))
        print(f'{total} bitmaps replaced -> {folder}')


if __name__ == '__main__':
    main()
