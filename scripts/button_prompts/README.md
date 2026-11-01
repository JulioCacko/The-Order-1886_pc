# Button prompt artwork

This folder holds only artwork made for this project; no game pixel is stored here.

- `marks/`: letter silhouettes (A, B, X, Y, LB, RB, LT, LS, RS, MENU, VIEW, SPACE, C, E, Q, SHIFT,
  TAB, 1). They were generated with an image model in the game's engraved serif style. `RT` was
  drawn by hand by the project owner. The Xbox set uses only each mark's shape; ink, softness and
  transparency come from the player's own texture.
- `keyboard/`: keycap, number-key, mouse and WASD drawings, generated with an image model in the
  game's monochrome hatched style. They are stored as 384 px grey + alpha.
- `plan.json`: for each of the 290 glyph bitmaps, the button it shows and its role per set
  (`face`, `label` or `keep`), reviewed against the source bitmaps. It holds no pixels.
- `keyboard-bindings.json`: the key layout the Keyboard and mouse prompts draw. The backend
  applies it with that set (`docs/order1886-button-prompts.md`).

`scripts/order1886_prompts.py` composes the selected set from the player's own game files.
