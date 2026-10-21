# Resolution: internal render size, output size and the no-FSR path

This page answers one question precisely, because the issue and the UI copy kept sliding
between two different measurements: **what renders the scene, and what presents it.**

## The two sizes

- **Internal render size.** The guest program decides this. The launcher does not set it
  and has no setting that changes it: `render_resolution` is written as `native` into
  `runtime.ini` (`order1886.py`, `write_runtime_config`) meaning "the guest's own size",
  not "4K".
- **Output size.** The size of the presented image. Graphics → **Output resolution** sets
  it: "Match the window" (the default, `output_res=automatic`) follows the window, and a
  fixed choice (`output_res=2560x1440` and so on) makes the presenter create its frame at
  that size, fitted to the game's aspect (`Presenter::SetExpectedGameSize`). FSR 1 and
  RCAS run at that size, and the final swapchain blit fits the result to the window. The
  runtime prints the chosen output at start (`Settings: output ...`).

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

## Native 4K: not supported, not claimed

Nothing in this project renders the scene at 3840×2160 today:

- `output_resolution` offers 3840×2160 as an **output**: the game's own frame upscaled by
  the Upscaling filter to that size. Its label says "upscaled, not native 4K".
- `tests/test_order1886_native_resolution.py` fails if an available choice mentions 3840 or
  4K without saying it is not native 4K, so a 4K claim cannot be smuggled in as a toggle.

Establishing native 4K feasibility needs a matched capture on real hardware: internal and
output dimensions, scaling settings, build and image quality recorded together. That is
the remaining acceptance work on #2, and this document deliberately does not pre-empt it.

## What to record in a report about resolution

1. The window size and the `output_res` in `runtime.ini`.
2. The internal size the runtime reports for that session (the runtime prints it; the
   launcher's Performance page reports configured values, not measured ones).
3. The `presentation_filter` in `runtime.ini`.
4. Whether the session used the linear path or a provider.
5. Build identity (source revision and runtime SHA256) and the GPU.

Without those five, two screenshots cannot be compared, which is exactly how "native 4K"
claims become unfalsifiable.
