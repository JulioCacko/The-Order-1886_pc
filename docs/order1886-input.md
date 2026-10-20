# Mouse, keyboard and direct play

These changes address the standard mouse-look path in issue #4 and the direct-play
entry point in issue #19. They are development changes following preview.3.

## Mouse look

Open **Game > Controls** in the launcher. Mouse look defaults to enabled. Adjust
**Mouse sensitivity (%)** and **Invert mouse Y**, save, then start the game.

- Mouse movement supplies the Po4 right stick. Left mouse supplies R2 (fire), and
  right mouse supplies L2 (aim), while the cursor is captured.
- **Esc** releases the cursor. **F6** captures or releases it again.
- Losing window focus, opening host UI, and entering text release capture and
  discard pending movement. Returning to the game restores capture unless you
  released it with Esc/F6.
- Controllers and keyboard input remain available. The stronger camera-axis
  input wins; adding a mouse does not disconnect or remap the controller.
- WAoD controls movement, arrow keys control the camera, I/J/K/L control the
  d-pad, and Enter supplies Options. The GUI's Escape-to-Home shortcut applies
  to the launcher; in the game window Esc releases the mouse.

The CLI also accepts `--mouse-look 0|1`, `--mouse-sensitivity 10..500`, and
`--mouse-invert-y 0|1`. Values reach the same `runtime.ini` settings as the GUI.
Mouse smoothing uses elapsed time rather than pixels per frame. This is
mouse-to-stick input: game stick acceleration and dead zones still apply.
An Order-specific direct 1:1 yaw/pitch hook, rebinding UI, and gameplay validation
of aiming/QTEs remain outstanding under #4.

## Direct play and desktop shortcuts

The portable package now includes **Play The Order 1886.exe**, sharing the same
dependencies as **The Order 1886.exe**. Keep both executables beside `_internal`
and `bin`; copying only the direct-play executable is insufficient.

1. Open the regular launcher, choose your game folder and settings, then save.
2. Use **Play The Order 1886.exe** to start with those saved preferences.
3. Use **Game > Create desktop shortcut** for a shortcut to this installation.
   Repeating the action updates the same shortcut. No shortcut is created until
   you choose that action.

Direct play uses the same backend command, preparation, runtime selection,
session lock, save backup and session-log worker as the GUI's Play action. First
run, missing game/runtime or unsupported settings open setup. otartup/runtime
failures report the exit code and session-log path. Relative saved paths resolve
from the installation, not the shortcut's working directory.

oource users can run `python launcher/order1886_launcher.py --play`. The desktop
shortcut action requires a built portable package. Real-game checkpoint and
long-session acceptance are separate from host/bootstrap and input fixtures.
