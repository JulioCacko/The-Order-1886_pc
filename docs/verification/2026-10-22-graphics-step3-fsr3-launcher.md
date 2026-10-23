# Graphics step 3 evidence: FSR 3.1 from the launcher (#10)

RTX 3070, Windows 11, branch `graphics/step3-fsr3-launcher` (`73623a9`), runtime built with
`bash build.sh --test` (56 native checks pass). Python suite: all pass, 19 skipped.

## What the player gets

Graphics → Upscaling → **AMD FSR 3.1 (native AA) + FSR 1**. Play writes:

```
presentation_filter=fsr1
upscaler=fsr3
```

The runtime loads `order1886_fsr3.dll` from its own folder and runs FSR 3.1.4 where the game's
temporal resolve ran (#94, `vk_order_resolve.cpp`). FSR 1 then scales the result to the output.
The game renders at its own size; render-target scaling and the quality presets are #3.

Other changes to the Upscaling choices:

- **Native temporal AA** is removed: the game's own temporal AA always runs, so the choice changed
  nothing.
- **DLSS, FSR 4 and the quality presets** each name what they still need.
- **Linux** keeps FSR 3.1 unavailable: its runtime does not load providers yet.

When the in-game menu saves `runtime.ini`, the runtime now writes `upscaler=` back. The launcher
reads `presentation_filter=fsr1` together with `upscaler=fsr3` as its own choice, so a menu save
no longer switches FSR 3.1 off. Both directions are covered by `tests/test_order1886.py`.

## Run

Both runs start from a copied save and go through the launcher's backend
(`tools/order1886_step1_evidence.py --only baseline upscaler-fsr3`, where `upscaler-fsr3` sets
`presentation_filter=fsr3` exactly as Play does). 60 FPS mode, VSync on, measured after 95 s in
the night courtyard.

| Upscaling | FPS | p50 ms | p99 ms |
| --- | ---: | ---: | ---: |
| FSR 1 (the game's own temporal resolve) | 53.23 | 18.22 | 35.99 |
| FSR 3.1 + FSR 1 | 53.50 | 18.25 | 31.85 |

Runtime log of the FSR 3.1 run:

```
Upscaler provider fsr3: AMD FSR 3.1.4 (FidelityFX SDK 1.1.4) available
Upscaler: fsr3 requested; AMD FSR replaces the game's temporal resolve, presenting with FSR 1
Upscaler: AMD FSR 3.1.4 (FidelityFX SDK 1.1.4) replaces The Order's temporal resolve at 1920x800 (native, depth inverted 0)
Upscaler: fsr3 reconstructed 7200 frames (1920x800, 2 samples, velocity scale 16)
```

No provider error was logged. FSR 3.1 costs nothing measurable here: the frame rate in this scene
is set by the CPU side of the runtime, not by the GPU.

The two runs reach the scene at slightly different moments, so their screenshots are not from the
same viewpoint. Neither shows ghosting or broken edges. The matched-viewpoint image comparison is
in the step 2 record (`docs/verification/2026-10-21-graphics-step2-evidence.md`): FSR 3.1 is
sharper on fine geometry.

## Packaging

`build.sh` builds `order1886_fsr3.dll` (`gpu/upscalers/fsr3`) and copies it beside the runtime.
`packaging/windows/order1886-go-build.ps1` copies it into the package's `bin/` and stops if it is
missing. The package workflow now checks out the `fsr-vulkan` submodule it needs.

## Not covered

- Camera near/far and field of view are still placeholders for FSR 3.1.
- The game's own resolve still runs before FSR 3.1, as a fallback.
- Linux, DLSS (#11), FSR 4 (#12) and XeSS (#13).
