# Graphics step 8: 90 FPS and unlocked engine timing (#14)

Branch `graphics/step8-frame-rate` (base `graphics/step1-cheap-wiring` at `9d951cd`). Runtime SHA256
`9eaf27e88d3926e697b723bf643d6396b0b1eca8d670309d7de6e5ce148b398a`, RTX 3070 (driver 617.14),
Windows 11, base game CUSA00076 APP_VER 01.00 / VERSION 01.03, eboot SELF SHA256 `a8ce5fe1…`.
Captured on 21 October 2026.

## Result

| Rate | Recipe | Launcher | Why |
| --- | --- | --- | --- |
| 30 | none (native) | available | baseline |
| 60 | `order1886-a8ce-engine-60-v1` (unchanged) | available, experimental | unchanged by this step |
| 90 | `order1886-a8ce-engine-90-v1`, 6 bytes | available, experimental | front end measured 90.0 FPS |
| Unlocked | `order1886-a8ce-engine-unlocked-v1`, 6 bytes | available, experimental | front end measured 120.0 FPS at the default cap |

90 and Unlocked are selectable as experimental, like 60, on the user's decision. Their gameplay timing is
as unaccepted as 60's: in the tested Chapter XI scene the game renders at about 5 FPS at every rate on
this GPU, so a QTE, physics, animation or audio check above 60 FPS is impossible here. The launcher
description and each launch's warning say so.

## How the engine times a frame

Headless Ghidra 12.1.4 against the existing `eboot-static.elf` project
(`out/order1886-language-ghidra-20261019`). Addresses are RVAs in the decoded image, which is also the
prepared `boot.bin` image offset.

- **Game clock** (`0x90eab0`, object at `0x16b1fd8`, constructed at `0x90e910`): each tick measures wall
  time in microseconds with `clock_gettime`, clamps it to `+0x50` = 66 666 us (15 FPS), scales it by the
  time scale at `+0x38`, and stores the step in seconds at `+0x3c` plus a running total at `+0x28`.
  Gameplay code reads `+0x3c` (for example `0x765850`), and timed events compare authored frame counts
  multiplied by 33 333 us against `+0x28` (`0x345b60`, `0x39e390`, `0x486880`, `0x68fff0`,
  `0x6bfb80`, `0xb0f550`). A fixed 33 333 us step exists only behind the `-fixedfps` developer
  argument (`0x447880`), which the shipped command line does not pass.
- **Rate**: the vblank interval global at `0x15c0d54`. The main loop (`0x1fd010`) builds its argument list
  from the literal `-frontend -syncinterval 2` (`0x1482726`). Init (`0x8a4074`) copies the parsed value
  when it is below 2. Five later writes reset it: `0x4507be`, `0x7658dd` and `0x765b6e` write 2, and
  `0x76590a` and `0x3f193a` write 1 while a scripted sequence plays (`0x765850`/`0x765a70`).
- **CPU pacer** (`0x835a60`): before each flip it queues a wait of
  `interval * 16666 us - elapsed - 2000 us` (`imul r14d, [0x15c0d54], 0x411a` at `0x835b9c`). At interval
  1 this alone holds the engine to 68 FPS.
- **Flip** (`0x877cf0`): `sceVideoOutSetFlipRate(interval - 1)` when the interval changes, then a flip in
  mode 3 (or 1). At interval 0 it never sets a flip rate and submits mode 2, an immediate flip. That is
  the engine's own uncapped mode.
- The remaining `1/30` and `1/60` float constants (`0xc850d0`, `0xc83030` and four others) budget
  particle emission from the step and are rate-independent.

So no simulation constant assumes 30 FPS; the 30 FPS rate is the interval global plus the pacer.

## Recipes

Both are hash-bound like the 60 FPS recipe (SELF, reconstructed ELF and metadata), check every site's
bytes before writing any, and patch only the derived `boot.bin`. Each `mov` is rebuilt from its RVA and
the global's RIP target, so a moved instruction cannot match.

| Site | 90 FPS | Unlocked |
| --- | --- | --- |
| `0x1482726` `-syncinterval 2` | `1` | `0` |
| `0x4507be`, `0x7658dd`, `0x765b6e` `mov [g], 2` | 1 | 0 |
| `0x76590a`, `0x3f193a` `mov [g], 1` | unchanged | 0 |
| `0x835b9c` pacer `0x411a` (16 666 us) | `0x2b67` (11 111 us) | unchanged (never waits at 0) |

The runtime warns once per flip mode instead of every frame, because Unlocked submits mode 2 every frame
(`video_out.cpp`, covered by `tests/test_order1886_flip_logging.py`).

## Measurements

`tools/order1886_step1_evidence.py` runs each rate once in an isolated state with a copy of the player's
`user/order1886/savedata` (CHAPTER XI - The United India House). The player's files are only read.

- `--continue-save 40` taps Space every 4 s from 40 s until the runtime logs
  `save data 'Playthrough00' mounted`. Fixed key times did not work across rates: boot and menu timing
  change with the rate, and the first unlocked runs never left the title menu, whose background is a
  live 3D scene.
- `--vsync 0`. The game window opens on the primary display, which is 3840×2160 at **60 Hz**. With VSync
  on (Fifo) every rate above 60 measured exactly 60.0 FPS: presentation blocked on the display and held
  the guest back. Changing vblank to 90 Hz or 480 Hz made no difference, so the runtime's vblank stays at
  60 Hz for every rate.

Guest flips per second, 10 s windows, `out/order1886-evidence/step8/novsync-rate-*` (not tracked):

| Rate | Save loaded | Front end | Chapter XI gameplay | Flip interval p50 |
| --- | --- | --- | --- | --- |
| 30 | no (12 taps, stayed on the menu) | 30.0 | — | 33.31 ms |
| 30 (earlier run, VSync on) | yes | 30.0 | 6–8.4 | 34.36 ms |
| 60 | yes | 60.0 | 4.3–7.3 | 17.00 ms |
| 90 | yes | **90.0** | 4.8–6.1 | 11.39 ms |
| Unlocked, cap 120 | yes | 90–112, then **120.0** for 70 s | 3.9–5.3 | 8.51 ms |

The log confirms each recipe (`changed_bytes` 6 for 90 and Unlocked), `VideoOut: frame limit 90 FPS` /
`120 FPS`, and `flipmode = 3` (90) or `flipmode = 2` (Unlocked) once each.

## Not verified

- Gameplay timing above 60 FPS: QTEs in Chapters 6 and 9, physics, animation and audio sync. The
  Chapter XI scene renders at 4–8 FPS at every rate, where the clock's 66.7 ms clamp already slows the
  game, so a higher rate cannot be observed in gameplay on this machine.
- The frame dumps of the 90 and Unlocked runs kept showing the title screen after the desktop screenshot
  showed gameplay, so the image comparison uses the desktop screenshots. The dump path was not
  investigated.

To accept 90 or Unlocked, measure a gameplay scene that renders above 60 FPS and check QTE timing there.
