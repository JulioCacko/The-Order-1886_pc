# The Order: 1886 display and timing investigation

## Result

The diagnostic path now prepares and records the selected aspect recipe independently of the frame-rate recipe. It records guest-frame trace summaries and dimensions and hashes for captured PNG and raw 32-bit frames. New launcher profiles default to original aspect and 30 FPS; explicit saved choices remain in effect.

The supplied options-menu defect and Chapter 6/9 QTE behavior are not fixed or accepted by this investigation. The available captures show startup/loading imagery, not the supplied menu or the affected QTE checkpoints. There is not enough evidence to select a guest-code, renderer or asset patch safely.

## Source findings

- The current aspect recipe changes four bytes at guest instruction RVA `0x44ce86` from float 2.4 to 16:9. It does not change UI geometry, clipping or assets.
- The fixed-1920x1080 UI helper belongs to a temporal upscaling path that the current Order runtime disables. The active rasterizer translates guest viewport and scissor values; no captured menu draw establishes a defect in that path.
- Game assets use hash-based paths under `_data/.../v11345526222/` and sampled containers start with `COMPRESS`. The codec and archive-to-asset mapping remain unidentified. Existing loose-file mod support does not mount these paths.
- The 60 FPS recipe changes an immediate byte at RVA `0x4507be` that selects the guest flip divisor. Static evidence supports frame pacing and flip submission. It does not identify or validate simulation timestep or QTE handlers.

## Runtime evidence

Four isolated probe runs were captured under `out/order1886-evidence/ui-fix-20261017/`: original/30, 16:9/30, original/60 and 16:9/60. Each captured a 1920x1080 guest/output frame and includes preparation receipts. These were bounded cold-cache startup runs; they are not same-menu comparisons and do not verify screen composition or campaign behavior.

The original/30 trace measured 29.4 guest flips/sec for 52.5 seconds with no repeated render serials. The 16:9/30 trace measured 29.3 guest flips/sec for 42.4 seconds with no repeated serials. The 60 FPS traces measured about 56.5 guest flips/sec and 56.3 render-work intervals/sec over 39.3 seconds, with 10 repeated render serials in the 16:9 run and four in the original run. These short startup traces do not meet the 30-minute timing gate and do not establish 60 distinct rendered gameplay frames.

The original game `eboot.bin` was used as input and remains unmodified. Probe preparation and captured output are in the ignored `out/` tree.

## Verification

- Graphics probe: 3 tests passed.
- Display recipe: 5 tests passed.
- Frame-rate recipe: 7 tests passed.
- Launcher: 11 tests passed.
- Desktop settings: 5 tests passed.
- Backend: 28 tests passed when rerun independently. A broader combined run had one watchdog timing failure (`test_watchdog_kills_and_reaps_child`); that failure did not reproduce in the isolated backend run.
- `git diff --check` passed.

## Evidence still needed before a game-code patch

- A matched capture of the supplied options menu at original and 16:9, with the parchment draw's target, viewport, scissor, vertices, UVs and sampled texture.
- Chapter 6 and 9 checkpoint saves or equivalent reproducible access, plus traces of guest frames, monotonic time, input, animation markers and QTE state transitions at 30 and 60 FPS.
- Asset codec and archive mapping evidence if the parchment dimensions prove asset-authored.
- A true 4K output run. These captures were 1920x1080.

Until those observations exist, retain both patches as opt-in and the 60 FPS warning. A forced pacing byte or guessed texture replacement would not meet the agreed success conditions.
