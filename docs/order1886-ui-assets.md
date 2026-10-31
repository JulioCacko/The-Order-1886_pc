# UI assets, controller glyphs and layout (CUSA00076 1.02)

This document records where The Order: 1886 keeps its UI and how
`tools/order1886_ui_extract.py` extracts it from the player's own dump. It covers the
DualShock 4 glyphs a replacement glyph set (Xbox, keyboard and mouse) would swap, and the
stage and placement data that UI re-anchoring needs when the letterbox is removed
(#1, #111). No game asset is stored in this repository.

## Summary

- The UI is Flash. The executable links RAD's Iggy, which parses SWF files at runtime
  ("creating from .swf"). There is no `.iggy` conversion step, no texture substitution for
  buttons and no button font.
- Every controller glyph is a SWF bitmap (`DefineBitsLossless2`, a few `DefineBitsJPEG3`)
  inside the movie that draws it. Glyphs are not GNF/GPU textures, so GNF tiling and BCn
  encoding do not apply. The bitmaps are exported as PNG. DDS output is not useful here.
- 17 movies sit in 9 `_data` resources. The menus, HUD, interaction prompts, QTEs, stealth
  takedowns and Lycan evade prompts are covered.
- In a live run, glyphs swapped through the existing mod overlay showed magenta in the
  menus and in QTEs. That run tested both supported injection forms (see Replacement).

## Containers

Resources live under `_data/1408209885/ps4/<area>/<namespace>/v<version>/<16-hex name>`.
`archivemap.bin` is a `u32` count followed by `(u64 name, u32 value)` records. The value
appears to group resources (it is recorded per resource in the manifest). The game loads a
resource and checks its first eight bytes:

- `COMPRESS`: a `u64` raw size, a `u64` size, then legacy Oodle data. Small resources are a
  single LZH/LZHLW stream; the size field is the payload size (file size - 24). Packages are
  a table of `(u64 raw offset, u64 size)` headers, each followed by an independently coded
  256 KiB chunk; there the size field is the whole file size.
- Anything else is used verbatim (`fde_c77f60` / `fde_c77d80` copy it as is).

Modern Oodle no longer decodes LZH, and no free decoder exists. The tool therefore runs the
game's own `OodleLZ_Decompress` (`0xe81790`) under Unicorn, loaded from the player's
`eboot.bin`. The tool first checks the SHA-256 of image bytes `0xe80000-0xec0000`, binds
imports to Python `memcpy`/`memmove`/`memset`, and supplies the Oodle allocator. It decodes
about 7 MB/s per process.

Inside a decoded package, each movie is a `u32` slot size followed by a SWF (`CWS`, zlib),
padded to 16 bytes. Other resources follow in the same payload.

## Movies

| Resource (`primary/...`) | Offset | Iggy app | Stage | Bitmaps | Glyph bitmaps |
|---|---|---|---|---|---|
| `c2d79afbc68fc86c/v1/e32dc7d7dc8151e2` | 0x4 | MenuApp | 1920x800 | 67 | 32 |
| `3861c21fc34b7612/.../baceeaafdf99323d` | 0x2844 | PublisherMenusApp | 1280x720 | 2 | 0 |
| same | 0xb5d4 | IndicatorApp (KI/QTE reticles, look hint) | 1920x800 | 8 | 0 |
| same | 0x13d44 | WeaponApp (weapons, ammo, evade/damage indicators) | 1920x800 | 126 | 1 |
| same | 0x14af84 | MenuApp (copy of the standalone menu) | 1920x800 | 67 | 32 |
| same | 0x31c024 | DebugApp | 1280x720 | 0 | 0 |
| same | 0x329fe4 | SubtitleApp | 1920x800 | 0 | 0 |
| same | 0x3329c4 | StealthApp (takedown Triangle) | 1920x800 | 22 | 14 |
| same | 0x34c664 | InteractApp (world prompts, hold, button mash, QTE, pickups) | 1920x800 | 598 | 132 |
| same | 0x576dd4 | ObjectiveApp | 1920x800 | 4 | 0 |
| `.../2fd49d9a5a7d4399` | 0x104 | CreditsApp | 1280x720 | 45 | 0 |
| `.../abf518b95fd9dd5a` | 0x71e04 | ChapterSelectionImagesApp | 1280x720 | 78 | 0 |
| `.../49aaa19f7cf28a03` | 0x3241584 | MorseCodeApp | 1920x800 | 5 | 0 |
| `.../0757a7b1def9877f` | 0x10c1264 | TheOrderApp | 1280x720 | 14 | 0 |
| `.../ec5e1979c41e637c` | 0x515fcb4 | CinemeleeApp (Lycan evade LS/RS) | 1920x800 | 26 | 13 |
| `.../9e417f9127f39ba6` | 0xcf55c4 | DemoScreensApp | 1280x720 | 2 | 0 |
| `.../d107aa37d606b0be` | 0x89584b4 | CinemeleeApp (second level) | 1920x800 | 26 | 13 |

`.../` is `primary/3861c21fc34b7612/v11345526222/`. A full `--scan-all` decoded every
candidate resource (all namespaces except audio, streamed texture mips and `GPU/`) and found
only these. `baceeaafdf99323d` is the shared UI package. The other `3861…` resources are
level packages whose movies load with their level.

## Controller glyphs

Glyph bitmaps are found through the symbols that draw them:

- `rad.widgets.buttons.ButtonIcon<Small|Large|32><Normal|Invert|Solid><Token>`: static icons
  in menus, prompts and tutorials.
- `<Movie>_fla.Button_<Token>_<Normal|Invert>_<BuildIn|BuildOut|BuildOutFail>`: animated
  prompt clips in InteractApp, StealthApp and CinemeleeApp. These are the QTE timed-press,
  hold and fail animations.
- `WorldInteractButtonPress<Token>`, `WorldInteractButtonMash`, `WorldInteractHold`,
  `WorldInteractQTE`, `InteractButtonMash`, `LycanEvadeButton<LS|RS>`: the QTE and
  interaction widgets that place those clips.

As the bitmaps show, `LS`/`RS` are the sticks (labelled L/R) and `LA`/`RA` are the stick
clicks (L3/R3). `LSF`/`LSB` are left stick forward/back. The manifest gives every bitmap a
`glyphs` list (each owning button) and sets `glyph` when that list has exactly one entry.
Ring, glow and frame layers that several buttons share get a list with more than one entry.

| Glyph | Movies with dedicated bitmaps |
|---|---|
| cross | MenuApp, InteractApp |
| circle | MenuApp, WeaponApp, InteractApp |
| square, l1, l2, r1, r2, r3, l3 | MenuApp, InteractApp |
| triangle | MenuApp, StealthApp, InteractApp |
| left_stick, right_stick | MenuApp, InteractApp, CinemeleeApp |
| left_stick_forward, left_stick_back, options | InteractApp |
| dpad_up/down/left/right | MenuApp, InteractApp |
| dpad_up_down, dpad_left_right, touchpad | MenuApp |
| cross_circle_swap | MenuApp (`ButtonIcon32InvertSwap`, follows the game's Cross/Circle swap) |

Other controller images:

- MenuApp bitmaps 194 and 197 (1920x800 JPEG3) are the DS4 diagrams in the Controls menu.
- Bitmaps 33 and 36 show the DS4 body for the touchpad options.
- Photo mode uses the small-scale icons.

These bitmaps belong to no button class and so carry no glyph tag. A replacement set must
still redraw them.

## QTE coverage

- **Live run:** a test mod tinted every glyph-tagged bitmap in MenuApp (standalone and
  package copy), InteractApp, StealthApp and WeaponApp. In-game, the title "PRESS ⊗", the
  menus and QTE prompts all showed magenta glyphs.
- **Not in the live run:** CinemeleeApp (Lycan evade LS/RS in `ec5e1979…` and `d107aa37…`)
  was not part of that mod. It uses the same `Button_Analog_*` clip structure.

Not glyphs, recorded so they are not mistaken for missing coverage:

- QTE timing rings and mash meters are vector shapes or neutral bitmaps (`QTEReticle`,
  `InteractButtonMash` progress).
- Prompt text is a separate text field. Subtitles use `htmlText` without `<img>`. No
  embedded font has private-use code points, so no prompt draws a glyph from a font.

## Replacement

1. Re-encode only the bitmap tags, keeping each character id. Prefer the original
   dimensions: the shapes' bitmap fill matrices map texture pixels to stage units, so a
   different size rescales the glyph unless the fill matrix changes with it.
   `DefineBitsLossless2` stores premultiplied ARGB.
2. Rebuild the SWF (CWS).
   - In the standalone menu resource (`c2d79…`), the movie is the whole file and may grow.
   - In packages, the movie must fit its slot. The `u32` slot size and the offsets of the
     following resources stay unchanged, and the rest of the slot is zero-padded. Glyphs with
     simple flat colours fit easily (the tint test saved space in every movie). Detailed
     art can run out of room (a straight RGB re-encode of JPEG3 glyphs did). Growing a slot
     would need the package index reverse engineered first.
3. Inject through the reversible mod overlay (`docs/order1886-mods.md`), mirroring the path
   under `_data`:
   - Standalone resources may be written raw (decoded, no `COMPRESS`); this loaded correctly.
   - Packages must stay `COMPRESS`. A raw `baceeaafdf99323d`, even unmodified, makes the
     game report an error and fault at boot. `stored_container()` writes a chunked
     `COMPRESS` of stored Oodle blocks (header byte `0x00`, memcpy). The game's own decoder
     accepts it, so no Oodle compressor is needed. An unmodified package wrapped this way
     booted cleanly.

## Proposed patch layout

```text
mods/
  Glyphs - Xbox/                 _data/... (c2d79…, baceeaafdf99323d, ec5e1979…, d107aa37…)
  Glyphs - Keyboard and mouse/   same resources, generated
```

- Ship a generator, not assets. It reads the player's dump with this tool, swaps glyph
  bitmaps from a glyph set of original or permissively licensed PNGs (one per glyph token
  above, plus the Controls diagrams), and writes the mod folders.
- Xbox mapping: cross→A, circle→B, square→X, triangle→Y, l1/r1→LB/RB, l2/r2→LT/RT,
  l3/r3→LS/RS click, sticks→sticks, options→Menu, touchpad→View.
- Keyboard and mouse glyphs depend on the player's bindings (`--keyboard-bindings`,
  `docs/order1886-input.md`). The launcher should regenerate that mod into the state
  folder whenever bindings change. Mouse buttons and the sticks (WASD/mouse) get fixed art.
  This also addresses the prompt half of #4.
- Launcher option "Button prompts: PlayStation / Xbox / Keyboard and mouse": it enables the
  matching generated mod at the end of the mod order, so it wins conflicts on those
  resources. PlayStation means no glyph mod.

## Layout data for removing the letterbox

The HUD, menu, interaction, stealth, objective, subtitle and Lycan movies all use a
1920x800 stage: the 2.4:1 band inside the letterbox. Credits, chapter images, publisher,
demo and debug screens use 1280x720. For each movie, the manifest records:

- the stage rectangle and frame rate;
- `root`: the main timeline's placements (depth, character, instance name, matrix with
  translation in pixels);
- every exported/AS3 symbol with its own placements and the bitmaps it draws.

Scaling the 1920x800 stage to a taller viewport moves every widget. Re-anchoring (#1, #111)
can use these placements to see which clips sit at the band's edges (reticles, objectives,
subtitles, weapon HUD). The anchoring itself happens either in the movies or in the Iggy
display size or scale mode the executable sets. Neither is changed here.

## Running the tool

```bash
python -m pip install unicorn
python tools/order1886_ui_extract.py "PATH/TO/CUSA00076" --output "PATH/OUTSIDE/REPO/ui"
python tools/order1886_ui_extract.py "PATH/TO/CUSA00076" --output "..." --scan-all --jobs 8
```

The default run decodes the 9 known resources (about 860 MB of payload, a few minutes on
one core). `--scan-all` decodes about 16 GB of payload across `--jobs` processes. The output holds `manifest.json` and, for each movie, `movie.swf`
(uncompressed, opens in JPEXS) and `bitmaps/<id>.png`. The tool refuses an output folder
inside the repository or the game folder and never writes to either.
