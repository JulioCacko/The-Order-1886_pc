"""Button prompts as a launcher option: build the selected set from the player's own dump.

The game's controller glyphs are SWF bitmaps (docs/order1886-ui-assets.md). No game pixel is
shipped: button_prompts/ holds only a reviewed plan (which bitmap shows which button, and its
role in the keyboard set) and the default key layout. At preparation the selected set is
composed from the player's own bitmaps:

- PlayStation: nothing is painted; the game's own DualShock 4 artwork is the default and is
  mounted unchanged.
- Keyboard and mouse: keycap, mouse and WASD drawings at the original bitmap size and position,
  showing the keys of the player's current keyboard mapping (the Controls page). A changed key
  shows on the next launch; the prompts never overwrite the bindings themselves (the rule
  upstream commit e25254e introduced: icons follow the map, not the other way round).

The Xbox prompt set was retired: the layout is the game's own or the keys you play with.

The result is cached under the state folder per executable, set, mapping and art version, and
mounted through the managed overlay after any enabled mods, so the selected prompts win.
"""
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import shutil

ASSETS = Path(__file__).resolve().parent / 'button_prompts'
SETS = ('playstation', 'keyboard')
RETIRED = ('xbox',)
VERSION = 4  # bump when the composition below changes (4: keyboard follows the live map; no Xbox)

# Menu discs drawn behind the controller icons: a keycap needs no disc behind it.
MENU_BACKINGS = {114, 276, 277, 285, 288}
# Tokens with no digital key of their own: the mouse and stick clusters (src/runtime_pad.c:
# mouse supplies R2 with the left button and L2 with the right; the sticks ride WASD/mouse).
CLUSTERS = dict(l2='RMB', r2='LMB', left_stick='WASD', right_stick='MOUSE',
                left_stick_forward='W', left_stick_back='S')
# The plan glyph token -> the binding id whose key presses it.
BUTTON_OF = dict(cross='cross', circle='circle', square='square', triangle='triangle',
                 l1='l1', r1='r1', l3='l3', r3='r3', options='options', touchpad='touchpad_left',
                 dpad_up='up', dpad_down='down', dpad_left='left', dpad_right='right',
                 cross_circle_swap='cross')
UNBOUND = '__unbound__'


def keyboard_bindings():
    """The default key layout the Keyboard prompts draw when the player changed nothing."""
    return json.loads((ASSETS / 'keyboard-bindings.json').read_text(encoding='utf-8'))


def key_label(name):
    """What a key cap shows for an SDL key name: 'Left Shift' -> 'SHIFT', 'Return' -> 'ENTER'."""
    key = (name or '').strip().casefold()
    short = {'left shift': 'SHIFT', 'right shift': 'R SHIFT', 'left ctrl': 'CTRL',
             'right ctrl': 'R CTRL', 'left alt': 'ALT', 'right alt': 'ALT GR',
             'left gui': 'WIN', 'right gui': 'WIN', 'return': 'ENTER', 'keypad enter': 'ENTER',
             'backspace': 'BKSP', 'escape': 'ESC', 'capslock': 'CAPS', 'delete': 'DEL',
             'insert': 'INS', 'pageup': 'PG UP', 'pagedown': 'PG DN', 'home': 'HOME', 'end': 'END'}
    if key in short:
        return short[key]
    if key.startswith('keypad '):
        return 'NUM ' + name.strip()[7:].upper()
    return name.strip().upper()


def keyboard_labels(bindings=None):
    """{glyph token: key cap text} for the keyboard set: the player's mapping over the
    default layout. An unbound button keeps the default key drawn (the runtime still answers
    it through the mouse or the other device)."""
    mapping = {k: v for k, v in keyboard_bindings().items() if v and v != UNBOUND}
    mapping.update({k: v for k, v in (bindings or {}).items() if v and v != UNBOUND})
    out = {token: key_label(mapping.get(button, button)) for token, button in BUTTON_OF.items()}
    out.update(CLUSTERS)
    out['dpad_up_down'] = out['dpad_up']
    out['dpad_left_right'] = out['dpad_left']
    return out


def plan(prompt_set):
    """{key: entry} with the reviewed glyph and this set's role. <set>_glyph overrides the
    glyph for one set."""
    entries = json.loads((ASSETS / 'plan.json').read_text(encoding='utf-8'))['bitmaps']
    return {e['key']: dict(e, role=e[prompt_set], glyph=e.get(prompt_set + '_glyph', e['glyph']))
            for e in entries}


# --- keyboard and mouse: drawn keycaps --------------------------------------------------------

@lru_cache(maxsize=None)
def drawing(glyph, label):
    """(image, kind) for a button in the keyboard set, drawn here (Pillow fonts, the game's
    off-white on dark palette): no bitmap art ships with the launcher."""
    import order1886_glyph_mod as glyphs
    icon = glyphs.draw_face(glyph, 'keyboard', label, 384)
    kind = {'l2': 'mouse-right', 'r2': 'mouse-left', 'left_stick': 'wasd',
            'right_stick': 'mouse-move'}.get(glyph, 'keycap')
    return icon, kind


def key_pair(labels, left, right):
    """Two single keycaps side by side, for a bitmap that shows a d-pad combination."""
    from PIL import Image
    import order1886_glyph_mod as glyphs
    caps = [glyphs.draw_face('face', 'keyboard', labels[p], 256) for p in (left, right)]
    gap = 14
    group = Image.new('RGBA', (sum(c.width for c in caps) + gap, max(c.height for c in caps)))
    x = 0
    for cap in caps:
        group.alpha_composite(cap, (x, (group.height - cap.height) // 2))
        x += cap.width + gap
    return group, 'key-pair'


def placed(e, icon, kind, wide=False):
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
    if kind == 'keycap' and wide:
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


def keyboard(entry, image, labels):
    # Menus show the keys that act there (Space selects, C goes back): the runtime has no
    # menu-aware mouse routing, so a left-click or Esc prompt would not be true.
    from PIL import Image
    if entry['key'].startswith('MenuApp-') and entry['id'] in MENU_BACKINGS:
        return Image.new('RGBA', image.size)
    if entry['glyph'] == 'dpad_up_down':
        icon, kind = key_pair(labels, 'dpad_up', 'dpad_down')
        return placed(entry, icon, kind)
    if entry['glyph'] == 'dpad_left_right':
        icon, kind = key_pair(labels, 'dpad_left', 'dpad_right')
        return placed(entry, icon, kind)
    label = labels.get(entry['glyph'], '')
    icon, kind = drawing(entry['glyph'], label)
    return placed(entry, icon, kind, wide=len(label) > 1)


# --- cached preparation ----------------------------------------------------------------------

def _fingerprint(game, prompt_set, labels):
    digest = hashlib.sha256(f'{VERSION}:{prompt_set}:'.encode())
    digest.update(json.dumps(labels, sort_keys=True).encode())
    for path in [Path(game) / 'eboot.bin', Path(__file__)] + sorted(p for p in ASSETS.rglob('*') if p.is_file()):
        digest.update(path.name.encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _base_is_stale(game, resource):
    """True when the base ps4/ tree holds a different copy of a file the PS4/ update tree also
    has: painting that resource would show base art while the executable checks the update."""
    import order1886_ui_extract as ui
    # NAMESPACE already ends in 'ps4' (ui.resolve uses it bare); the update sibling
    # sits beside it. Appending 'ps4'/'PS4' here looked under .../ps4/ps4 and never fired.
    namespace = Path(ui.NAMESPACE)
    base = Path(game) / namespace / resource
    sibling = Path(game) / namespace.parent / 'PS4' / resource
    return (base.is_file() and sibling.is_file()
            and hashlib.sha256(base.read_bytes()).digest()
            != hashlib.sha256(sibling.read_bytes()).digest())


def prepare(game, state, prompt_set, log=print, bindings=None):
    """[(path relative to the game folder, generated file)] for the selected set; empty for the
    game's own PlayStation prompts. Built once per executable, set, key mapping and art version.
    A retired set ('xbox') launches with the original layout and a note instead of failing."""
    if prompt_set in RETIRED:
        log(f'{prompt_set.capitalize()} button prompts were retired; using the '
            "game's own PlayStation prompts.")
        return []
    if prompt_set not in SETS:
        raise ValueError(f'Button prompts must be one of {", ".join(SETS)}')
    root = Path(state) / 'button-prompts'
    if prompt_set == 'playstation':
        return []
    try:
        import numpy  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError as error:
        raise ValueError(f'{prompt_set.capitalize()} button prompts need {error.name or error}'
                         f'; this installation was built without it. ({error!r})') from error
    import order1886_glyph_mod as glyphs
    import order1886_ui_extract as ui
    _NAMESPACE = ui.NAMESPACE
    labels = keyboard_labels(bindings)
    folder = root / prompt_set
    stamp = folder / 'stamp.json'
    fingerprint = _fingerprint(game, prompt_set, labels)
    try:
        recorded = json.loads(stamp.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        recorded = {}
    built = folder / glyphs.SETS[prompt_set]
    if recorded.get('fingerprint') != fingerprint or not all((built / f).is_file() for f in recorded.get('files', [])):
        log(f'Building {prompt_set} button prompts from your game files (first use only)...')
        reviewed = plan(prompt_set)
        resources = sorted({e['resource'] for e in reviewed.values() if e['role'] != 'keep'})
        missing = [r for r in resources if ui.resolve(game, r) is None]
        if missing:
            raise ValueError('Button prompts are verified with CUSA00076 1.02; this game has no '
                             + ', '.join(missing) + '. Choose PlayStation prompts.')
        stale = [r for r in resources if _base_is_stale(game, r)]
        if stale:
            raise ValueError('The update was extracted beside the base game without merging it; '
                             "painting prompts now would show the old buttons. Run "
                             "scripts/order1886_merge_update.py on this game folder first "
                             "(see docs), or choose PlayStation prompts: " + ', '.join(stale))
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
        try:
            _, total = glyphs.build(str(game), prompt_set, str(folder), plan=reviewed,
                                    log=lambda line: None,
                                    painter=lambda entry, image: keyboard(entry, image, labels))
        except SystemExit as error:  # the decoder refuses an unverified executable
            raise ValueError(f'{error} Choose PlayStation prompts.') from None
        files = sorted(str((p.relative_to(built))) for p in built.rglob('*') if p.is_file())
        recorded = dict(fingerprint=fingerprint, files=files)
        temporary = folder / 'stamp.tmp'
        temporary.write_text(json.dumps(recorded, indent=1), encoding='utf-8')
        os.replace(temporary, stamp)
        log(f'{prompt_set.capitalize()} button prompts ready: {total} bitmaps.')
    return [(Path(f), built / f) for f in recorded['files']]
