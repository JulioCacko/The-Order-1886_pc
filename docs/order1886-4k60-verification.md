# 4K / 60 FPS acceptance

The user approved these decisions on 16 October 2026:

- 3840x2160 output through the existing FSR1 spatial upscaler is acceptable.
- Preserve at least the original 1920x800 scene detail, effects and letterboxing.
- Experimental 60 FPS is opt-in. Keep native 30 FPS as recovery.
- Timing changes take effect at launch and require restart. Automatic chapter/QTE switching is deferred.
- Acceptance requires 30 minutes of representative gameplay: average >=59 FPS,
  p99 frame time <=20 ms, correct game speed/audio/input, and working save/load.
- Report cold-cache and warm-cache results separately.

## Timing recipe

`scripts/order1886_frame_rate.py` validates the original SELF and reconstructed ELF
hashes, game metadata, PS4BOOT2 bounds, complete instruction and RIP-relative target.
It changes one byte in derived preparation output before linking. Preparation
identity includes the selected rate and recipe; returning to 30 rebuilds the native
image. Original game files are preserved.

This adapts illusion's published 01.02 recipe to the exact local 01.00/01.03
executable hash. The published recipe warns of QTE softlocks in Chapters 6 and 9.
Campaign behavior remains unverified. The game can legitimately change its timing
divisor during transitions; the runtime does not continuously force that global.

## Evidence boundary

`out/order1886-evidence/4k60-audit/experimental-60-freeze.json` records the real
60-to-30-to-60 preparation and cache-reuse proof. The original SELF hash stayed
unchanged; linked native and experimental images differ by one byte.

`user/order1886/diagnostics/srt-bounded-null-4k-cold` contains an actual
3840x2160 intro capture with FSR1 and the 30 FPS engine profile. That older run
exposed an FSR output-layout error and overflowing texture-layout/upload arithmetic.
It does not establish menu, gameplay, 60 FPS, or the acceptance metrics above.

The `e361df5d...` integration build and eight native checks passed. Its cold run,
`user/order1886/diagnostics/image-bounds-4k-cold`, produced another 3840x2160
intro capture and exited explicitly at a ReadConst pointer assertion after 27.636
seconds. The FSR output-layout callback did not recur. All 149 dumped SPIR-V
modules passed Vulkan 1.3 validation. Two integer-sampler callbacks remain. The
older oversized resource was not reached in this schedule; guard intervention
has not been observed in-game.

The isolated Python suite passed 163 tests (152 passed, 11 skipped) after the
Windows lifecycle fixtures were corrected to launch a direct interpreter process.
The log is `out/order1886-evidence/image-bounds-python-tests.log`.

Diagnose the failing ReadConst pointer and the exact oversized descriptor before
making a performance claim. Required menu/gameplay and acceptance metrics remain
unverified.
