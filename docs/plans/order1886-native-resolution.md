# Native render resolution (#3, #2)

Goal: the game renders at the size the player picks, up to native 4K, with no upscaler in the
path. Agreed 2026-10-29.

## Decisions

- **Mechanism.** The game sizes its own targets. A prepare-time recipe
  (`scripts/order1886_resolution.py`) edits the derived `boot.bin` only, after checking the
  original bytes at every site:
  - the engine's display-mode switch at RVA `0x44cef3`. Retail has three hard-coded modes
    (1280x720, 1920x1080, 3840x2160) selected by flag bits it never sets. The recipe always takes
    the 720p branch and rewrites its output and viewport sizes, as the published 900p/720p patch
    does.
  - the renderer's base scene size, `mov edi, 1920; mov esi, 800` at `0x839c54`/`0x839c59`. It is
    stored in the device at `+0x738`/`+0x73c` and sizes scene depth. Without it, depth stays 1920x800
    while colour follows the new size, and the frame stops after six passes. The same mismatch
    explains the 16:9 patch's "native 1080p will cause visual issues" note.
  - the render-target stack `GpuStack.RenderTargets` (`0xca5dc0`): fixed partitions of
    162/19/73 MiB for 1920x800. A larger frame overflows the first into the shared ones and
    live targets overlap (TAA history corrupted, NaN through the post chain). Each partition
    scales with the scene's pixel count, and the 654 MiB GPU heap it is carved from
    (`0x298d0b`) grows by the same amount; the launcher raises `ORDER1886_DMEM_MB` to match.
  - Renderer-side overrides are allowed only for what no game patch reaches; none was needed.
- **Size.** The player picks a width, from presets or a custom value: a multiple of 16 from 1280 to
  4880 (4192 with 16:9). The signed 32-bit immediates of the stack and heap sites set that cap;
  larger sizes need a code cave. The frame is width x width*9/16. The scene inside it follows the
  aspect setting: width/2.4 for Original (3840x1600) and the full frame for 16:9 (3840x2160).
- **Scope.** Every screen-sized pass scales, and half-res chains keep their ratio. Shadow maps get
  their own setting (original / 2x / 4x, default 2x above 1080p), in phase 2.
- **Upscalers.** DLSS and FSR are set aside while the render size is not the original;
  the frame is presented 1:1.
- **MSAA.** It must match what the PS4 resolves: read the guest AA registers, and if the game uses
  EQAA, run 4x on the host. A launcher option offers "PS4 / 2x", falling back to 2x above 1440p
  if 4x misses 30 FPS. This is phase 3.
- **Memory.** Testing showed the need: guest direct memory is raised by the GPU heap's growth
  (5818 MiB at 3840x1600, 6176 MiB at 3840x2160). The original size keeps retail 5056 MiB.
- **Performance.** A steady 30 FPS on an RTX 3070-class GPU is required. The 60 FPS patch must keep
  working, but frames may drop.
- **Builds.** 1.02 first. 1.00 comes in phase 4: recipes find sites by byte signature instead of a
  fixed RVA, starting with a check that 1.00 boots.
- **Proof.** RenderDoc in three scenes (courtyard, Chapter II "Evidence", Chapter 1 "Even
  Watchful"), plus frame-census target sizes, logged FPS and a verification doc under
  `docs/verification/`.

## Phases (one PR each)

1. Size recipe on 1.02 (size, scene size, render-target stack, GPU heap), launcher width option,
   automatic guest memory, docs and the native-resolution guard test. 16:9 at 3840x2160 rendered
   clean in the same work, so phase 2 folded into phase 1.
2. Shadow-map resolution setting, after the #122 shadow fix merges.
3. MSAA matched to the guest, plus its option.
4. 1.00 support through signature-located sites.
