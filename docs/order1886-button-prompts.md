# Button prompts: PlayStation, Xbox, keyboard and mouse

**Controls > Button prompts** chooses the buttons the game draws in prompts, menus, quick-time
events, stealth takedowns and Lycan evades. The setting applies on the next launch.

| Choice | Result |
|---|---|
| PlayStation (original) | The game's own artwork. Nothing is built. |
| Xbox | A, B, X, Y, LB, RB, LT, RT, LS, RS, Menu and View. The stick and D-pad artwork is the game's own, because both pads have the same controls there. |
| Keyboard and mouse | Keycaps, mouse buttons and a WASD cluster that match the layout below. Choosing it also applies that key layout. |

## How it works

The prompts are bitmaps inside the game's Flash UI movies (`docs/order1886-ui-assets.md`). When
Xbox or Keyboard and mouse is selected, the first launch builds the artwork from your own game
files. This takes from a few seconds (Xbox) to about a minute (keyboard, which also covers two
Lycan levels). The result is cached in your player data under `button-prompts/` and rebuilt
only when the game executable or the prompt artwork changes. The built files are mounted
through the same reversible overlay as mods, after any enabled mods, so the selected prompts
take priority. The original game files are never changed.

- **Xbox:** each original texture is kept, and only its PlayStation marking is replaced, inside
  an explicit edit region, by the matching letter. The letter takes the ink, softness and
  transparency of the original. Every pixel outside that region is the game's own.
- **Keyboard and mouse:** keycap and mouse drawings in the game's engraved style. They are
  placed at each original bitmap's size and position. Animation layers such as rings, glows
  and fail splats stay the game's own.

The repository ships only its own artwork (`scripts/button_prompts/`: letter marks, keycap and
mouse drawings, made with an image model, plus one hand-drawn RT label). It also ships a
reviewed plan listing which bitmap shows which button. No game pixel is shipped.

## Keyboard and mouse layout

Choosing Keyboard and mouse replaces any custom keyboard buttons with this layout, so the
prompts always show the keys that act. Mouse movement is the camera (Mouse camera must be on).
Left click fires (R2) and right click aims (L2).

| Action | Key | Game button |
|---|---|---|
| Move | W A S D | Left stick |
| Vault, climb, leave cover; select in menus | Space | Cross |
| Enter cover, contextual evade; back in menus | C | Circle |
| Reload | R | Square |
| Interact, melee, takedown | E | Triangle |
| Blacksight | Q | L1 |
| Alternate fire | Y | R1 |
| Sprint | Left Shift | L3 |
| Objectives | X | R3 |
| Pause | Esc | Options |
| Camera bias | Tab | Touchpad (left) |
| Primary weapon / sidearm | 1 / 2 | D-pad right / left |
| Frag / smoke grenade | 5 / 6 | D-pad down / up |

The keyboard's own R and F trigger keys are unbound, so R reloads without aiming. Esc also
releases the mouse cursor (F6 captures it again).

Not done yet: left click to select and Esc to go back inside menus. The runtime cannot tell a
menu from gameplay, where left click fires, so menus show the keys that work there (Space and
C).

## Limits

- The packaged worker carries Pillow, numpy and Unicorn to build the artwork. A source
  checkout needs `python -m pip install unicorn numpy "Pillow>=10.1"`.
- Only the 1.02 executable (CUSA00076) is verified. Building stops with a clear message on
  another build.
- The Controls-menu controller diagrams are full illustrations and stay the game's own.
