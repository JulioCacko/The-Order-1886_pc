# Button prompt artwork

This folder holds no artwork and no game pixel: the keycaps are drawn at build time with
Pillow fonts, in the game's own palette.

- `plan.json`: for each of the 308 glyph bitmaps, the button it shows and its role in the
  keyboard set (`face`, `label` or `keep`), reviewed against the source bitmaps. It holds no
  pixels. It also names bitmaps that no button class owns but that show a button (the weapon
  HUD's R1 and R2, the button-mash crosses); `keyboard_glyph` overrides the glyph for that set.
- `keyboard-bindings.json`: the default key layout the Keyboard and mouse prompts draw when
  the Controls page changes nothing. With custom bindings the prompts follow them instead.

`scripts/order1886_prompts.py` composes the selected set from the player's own game files.
PlayStation prompts (the default, and the original layout) paint nothing: the game's own
DualShock 4 artwork ships with every edition. The Xbox set was retired.
