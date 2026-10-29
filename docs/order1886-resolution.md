# Resolution: internal render size, output size and the no-FSR path

This page answers one question precisely, because the issue and the UI copy kept sliding
between two different measurements: **what renders the scene, and what presents it.**

## The two sizes

- **Internal render size.** The game decides it, from a size the launcher can now set:
  Graphics → **Render resolution** (below). At the original setting `render_resolution` is
  written as `native` into `runtime.ini` (`order1886.py`, `write_runtime_config`), meaning
  "the guest's own 1920×800". Any other setting writes the scene size the game renders,
  for example `3840x1600`.
- **Output size.** The size of the presented image. Graphics → **Output resolution** sets
  it: "Match the window" (the default, `output_res=automatic`) follows the window, and a
  fixed choice (`output_res=2560x1440` and so on) makes the presenter create its frame at
  that size, fitted to the game's aspect (`Presenter::SetExpectedGameSize`). FSR 1 runs
  only when the game's image is smaller than that size in both dimensions. Sharpening
  (RCAS) runs with that FSR 1 pass, or alone when the image already matches the output
  size. With Linear and a larger output, neither runs, so there is no sharpening on that
  path (`Ps4Graphics::FsrPassRuns`). The final swapchain blit fits the result to the
  window. The runtime prints the chosen output at start (`Settings: output ...`).

A larger output does not make the scene render larger, and a smaller output does not make
it render smaller. Any claim that one implies the other is wrong.

## The original-resolution, non-FSR path

Graphics → **Upscaling** → **Linear / no FSR**.

That selection is written to `runtime.ini` as `presentation_filter=linear` and is the only
path that performs no presentation scaling beyond the display's own. It is available, it
persists across restarts like every other setting, and it does not require a temporal
provider. `tests/test_order1886_native_resolution.py` fixes that contract, including that
`render_resolution` stays `native` in both the linear and FSR 1 cases.

## What FSR 1 does here

`presentation_filter=fsr1` (the default) is presentation-side scaling of an already
finished frame. It is not a temporal upscaler, it does not have depth, motion, jitter or
history inputs, and selecting it does not change the internal render size. The temporal
providers that do use those inputs (DLSS, FSR 3.1, FSR 4, XeSS, native TAA) are listed in
the same selector but carry an availability reason: the validated temporal inputs they
need are tracked in #7, and the providers themselves in #10–#13.

## Native render resolution (#3)

Graphics → **Render resolution** makes the game itself render at a larger (or smaller)
size: Original (1920 wide), 2560, 3840 (native 4K) or a custom width (multiple of 16, 1280
to 4880; 4192 with 16:9 framing). The height follows **Framing**: width/2.4 for Original
(3840×1600, letterboxed into 3840×2160) and the full 16:9 frame for 16:9 (3840×2160).

How (`scripts/order1886_resolution.py`, applied to the prepared copy of the executable,
every site byte-checked first, original files unchanged):

- the engine's display-mode switch (RVA `0x44cef3`) has fixed 720p, 1080p and 2160p modes
  that retail never selects; the recipe always takes the 720p branch, as the published
  900p/720p patch does, and writes the chosen size into its output and viewport stores;
- the renderer's base scene size (`mov edi, 1920; mov esi, 800` at `0x839c54`), which
  sizes scene depth;
- the render-target stack `GpuStack.RenderTargets` (built at `0xca5dc0`). It has fixed
  partitions for 1920×800: 162 MiB, 19 MiB and 73 MiB, the last two shared by sub-stacks
  used at different times. A larger frame overflows the first into the others and live
  targets overlap (corrupted TAA history, then NaN through the post chain). Each
  partition scales with the scene's pixel count;
- the GPU heap the stack is carved from (`0x28E00000`, allocated at `0x298d0b`), grown
  by the same amount. The launcher raises guest direct memory to match
  (`ORDER1886_DMEM_MB`, 5818 MiB at 3840×1600).

The signed 32-bit immediates of those sites cap the width (4880 Original, 4192 16:9).

Above the original size Upscaling is set aside: `presentation_filter=linear`, no temporal
provider, the frame presented 1:1. `tests/test_order1886_native_resolution.py` fixes that
contract and that no other setting can claim native 4K; `output_resolution` 3840×2160 is
still an upscaled **output** of whatever the game rendered.

Evidence: `docs/verification/2026-10-29-native-resolution.md`.

## What to record in a report about resolution

1. The window size and the `output_res` in `runtime.ini`.
2. The internal size the runtime reports for that session (the runtime prints it; the
   launcher's Performance page reports configured values, not measured ones).
3. The `presentation_filter` in `runtime.ini`.
4. Whether the session used the linear path or a provider.
5. Build identity (source revision and runtime SHA256) and the GPU.

Without those five, two screenshots cannot be compared, which is exactly how "native 4K"
claims become unfalsifiable.
