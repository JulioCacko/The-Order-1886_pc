# Button prompt art guide (Xbox, keyboard and mouse)

This guide covers making replacement button prompt art for The Order: 1886. The art can come
from an image model (ChatGPT/GPT image, others) or be drawn by hand. The art is then turned
into a mod with `tools/order1886_glyph_mod.py`. No game asset is stored in this repository:
the sources come from your own dump, and you choose what to share.

Background on formats and injection: `docs/order1886-ui-assets.md`.

## 1. Make the art request pack

```bash
python -m pip install unicorn
python tools/order1886_glyph_mod.py pack "PATH/TO/CUSA00076" --output "PATH/OUTSIDE/REPO/glyph-pack"
```

The pack holds:

| File | Purpose |
|---|---|
| `sources/<key>.png` | Every controller-glyph bitmap from the four UI resources, at its real size. `<key>` is `<App>-<movie offset>-<bitmap id>`, for example `InteractApp-34c664-1033`. |
| `contact-sheet.png` | Every bitmap with its key, suggested role and glyph. Green means face, blue means label, grey means keep. |
| `plan.json` | One entry per bitmap. `glyph` and `role` are editable, and `build` follows them. |
| `GPT-PROMPTS.md` | The exact image list for both routes below, with sources and return file names. |

## 2. Review the plan (5 minutes, worth it)

Open `contact-sheet.png` next to `plan.json`. The suggestions come from image statistics and
from RAD's class names, and both have known errors:

- **Roles.** Each bitmap is a `face` (a whole button icon), a `label` (text or a mark drawn
  over a blank body: `R3`, `L1`, `X`, a triangle), or `keep` (rings, wipes, glows, black
  masks, red fail splats, blank button bodies). A blank body marked `face` will get a label
  that the overlay then duplicates. A labelled face marked `keep` stays PlayStation.
- **Glyphs.** Trust the source image, not the name. The game's own class names disagree in
  places. For example, the bitmaps under `ButtonIconLargeNormalLS` show "L3", and an R2
  icon contains the "R3" text.

Glyph values: `cross circle square triangle l1 r1 l2 r2 l3 r3 left_stick right_stick
left_stick_forward left_stick_back dpad_up dpad_down dpad_left dpad_right dpad_up_down
dpad_left_right touchpad options cross_circle_swap`.

Glyph mapping:

| PlayStation | Xbox | Keyboard and mouse (runtime defaults) |
|---|---|---|
| Cross | A | Space |
| Circle | B | Left Shift |
| Square | X | E |
| Triangle | Y | Q |
| L1 / R1 | LB / RB | 1 / 3 |
| L2 / R2 | LT / RT | Right mouse / Left mouse |
| L3 / R3 | LS / RS (stick click) | Z / C |
| L stick, R stick | left / right stick | WASD / mouse |
| L stick up / down | left stick up / down | W / S |
| D-pad | D-pad | I / K / J / L |
| Touchpad | View | Tab |
| OPTIONS | Menu | Enter |

The keyboard set follows your bindings when you pass `--keyboard-bindings` (the same JSON
the launcher saves). Regenerate the mod after changing bindings.

## 3. The look to match

The prompts are monochrome engravings. Match these traits in every image:

- Off-white body (about `#EDEDED`) with fine diagonal cross-hatching for shading, a thin dark
  outline, and highlights that fade to transparency at the edges.
- Labels are near-black (about `#141414`) bold serif capitals on normal icons. Overlay
  labels are off-white serif capitals with a dark outline.
- "Invert" variants swap the body and label tones. The tool detects them and inverts
  per-glyph art itself, so request the normal tone only (route A).
- No colour. Xbox's coloured letters (green A, red B and so on) clash with the art
  direction; ask for monochrome.
- Transparent background (real alpha, no checkerboard), the subject centred, no drop shadow,
  no logos and no extra text.

Sizes: most sources are 32x32 or 64x64; a few are larger. Request 512x512 or 1024x1024; the
tool scales art down into each source's opaque area. For route B, ask for the source's own
size or a clean 4x multiple of it.

## 4. Route A: one image per button (quick)

`GPT-PROMPTS.md` lists the buttons the plan uses. For each button and set, produce:

- `art/<set>/<glyph>.png`: the whole button (used for `face` bitmaps);
- `art/<set>/<glyph>_label.png`: the label or mark alone (used for `label` bitmaps).

`<set>` is `xbox` or `keyboard`. Attach one or two of the listed sources as the style
reference. Prompt A (face):

> Create a 1024x1024 PNG with a fully transparent background. Draw a single game
> button-prompt icon: {SUBJECT}. Match the attached reference icons exactly in rendering
> style: monochrome engraved look, off-white body with fine diagonal cross-hatching, thin dark
> outline, near-black bold serif capital label, centred, filling about 85% of the canvas.
> Do not copy the PlayStation symbol from the reference; use the label I give. No colour, no
> drop shadow, no background, no other text.

Prompt A (label):

> Create a 1024x1024 PNG with a fully transparent background containing only the text
> "{LABEL}" in off-white bold serif capitals with a thin dark outline, centred, filling about
> 70% of the width, in the engraved style of the attached reference. No button shape, no
> background, no other marks.

Subjects:

- Face buttons: `round button labelled "A"` (B, X, Y).
- Bumpers: `flat rounded-rectangle bumper labelled "LB"`.
- Triggers: `trigger shape (trapezoid, wider at the bottom) labelled "LT"`.
- Sticks: `thumbstick cap seen at a slight angle, labelled "L"`. Clicks use "LS"/"RS".
  Stick up/down: `... with a small arrow pointing up/down`.
- D-pad: `plus-shaped D-pad, the {up|down|left|right} arm filled dark`. Both arms for
  up_down and left_right.
- Menu / View: `small round button with the three-line menu symbol` / `... with the
  two-overlapping-squares view symbol`.
- Keyboard: `square keycap labelled "E"`. Use a wide keycap for SPACE, SHIFT, ENTER, TAB.
- Mouse: `computer mouse outline seen from above, the {left|right} button filled dark`.

## 5. Route B: redraw each source exactly (best match)

For a pixel-faithful result, redraw individual sources. `GPT-PROMPTS.md` lists every face
and label bitmap with its key, size and target text. Save each result as
`art/<set>/bitmaps/<key>.png`; it is used as is, only resized to the source size. Mix the
routes freely: a route B image wins over route A for its bitmap, and anything missing is
drawn by the tool. Prompt B:

> Edit the attached image. Keep the exact canvas size, framing, transparency, lighting,
> cross-hatching, outline and overall shape. Replace only the PlayStation marking "{SHOWS}"
> with "{TARGET}" ({DESCRIPTION}), drawn in the same style, weight and tone as the original
> marking. Do not add colour, shadows, background or any other change. Return a PNG with
> real alpha.

Check that the result really has transparency. Some models paint a checkerboard; reject
those images.

## 6. Build, install, test

```bash
python tools/order1886_glyph_mod.py build "PATH/TO/CUSA00076" --set xbox \
    --mods "PATH/TO/mods" --plan "PATH/TO/glyph-pack/plan.json" --art "PATH/TO/glyph-pack/art"
python tools/order1886_glyph_mod.py build "PATH/TO/CUSA00076" --set keyboard \
    --mods "PATH/TO/mods" --plan "PATH/TO/glyph-pack/plan.json" --art "PATH/TO/glyph-pack/art" \
    --keyboard-bindings "{}"
```

This writes `PATH/TO/mods/Glyphs - Xbox` and `Glyphs - Keyboard and mouse`. In the
launcher, open **Advanced**, select that mods folder, enable one glyph folder (enabling both
lets the later one win), save, and start the game.

What to check: the title "PRESS ...", the menu footer prompts, Controls and Photo mode, a
world interaction prompt, a QTE (timed press, hold, button mash), a stealth takedown and a
Lycan evade.

Limits:

- Each movie inside the shared UI package must fit its original slot. Detailed photographic
  art can overflow it, and `build` then stops with the movie and byte counts. Flat,
  high-contrast art compresses best.
- Character ids and bitmap sizes never change, so placement and animation stay the game's.
- The Controls-menu controller diagrams (MenuApp bitmaps 194/197) and the DS4 body images
  (33/36) are full illustrations, not glyphs. They are outside this pipeline; redraw them by
  hand if you want them changed.
