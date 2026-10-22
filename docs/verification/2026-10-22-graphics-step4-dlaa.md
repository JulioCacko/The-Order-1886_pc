# Graphics step 4 evidence: NVIDIA DLAA through the provider path (#11)

RTX 3070, Windows 11, branch `graphics/step4-dlss`. `order1886_dlss.dll` is built with MSVC 2022
from `gpu/dlss_bridge` against NVIDIA's DLSS SDK 310.9.16 (`gpu/dlss_bridge/build.ps1`, pinned
archive SHA-256 `418d6c68…`, runtime `nvngx_dlss.dll` 310.9.16.0). Its three CPU contract tests
pass.

## What changed

- **Instance and device extensions.** DLSS needs Vulkan instance and device extensions. The
  runtime now loads the selected provider before the instance exists, asks it for both lists, and
  enables the ones the driver offers (`vk_platform.cpp`, `vk_instance.cpp`,
  `vk_upscale_providers.cpp`). Only the selected provider gets its extensions, so every other
  session's Vulkan setup is unchanged.
- **DLAA at 1:1.** The bridge now requests NGX's DLAA mode when the render size equals the output
  (it requested Max Quality before). Preset K, auto-exposure, HDR, low-resolution motion vectors.
- **Provider output.** The provider's output image is also a transfer destination: NGX clears it
  with a transfer.
- **Camera far plane.** It is a finite 1000 instead of 0: DLSS checks far > near even with
  infinite depth.
- **Launcher.** Upscaling → **NVIDIA DLAA (DLSS at native size) + FSR 1** writes `upscaler=dlss`.
  On a GPU without DLSS the provider reports itself unavailable, the game's own anti-aliasing
  stays and the log says why. Linux keeps it unavailable.
- **Windows package.** It ships the bridge, `nvngx_dlss.dll` and NVIDIA's license
  (`notices/NVIDIA-DLSS-LICENSE.txt`) whenever `build.ps1` staged them beside the runtime.

## Run

Night courtyard from a copied save, 60 FPS mode, measured after 95 s. The runs go through the
launcher's backend, as Play does.

```
Upscaler provider dlss: DLSS 310.9.16 / preset K available
Upscaler: dlss requested; DLSS replaces the game's temporal resolve, presenting with FSR 1
Upscaler: DLSS 310.9.16 / preset K replaces The Order's temporal resolve at 1920x800 (native, depth inverted 0)
Upscaler: dlss reconstructed 5400 frames (1920x800, 2 samples, velocity scale 16)
```

| Upscaling | FPS | p50 ms | p99 ms | Run |
| --- | ---: | ---: | ---: | --- |
| FSR 1 (the game's own temporal resolve) | 55.07 | 17.36 | 25.77 | rerun |
| FSR 3.1 + FSR 1 | 51.04 | 18.53 | 28.55 | rerun |
| NVIDIA DLAA + FSR 1 | 47.75 | 19.12 | 28.73 | first run |

DLAA costs about 2.5 ms per frame on the RTX 3070 at 1920×800, and FSR 3.1 about 1.3 ms. No
provider error was logged in any run.

The DLAA row comes from the first run. In the rerun, DLAA's session stopped presenting at 57 s
before the measured window began. One earlier session with no upscaler stopped the same way at
81 s, so this intermittent freeze is not caused by the provider; it is tracked separately.

## Not covered

- A matched-viewpoint image comparison between DLAA, FSR 3.1 and the game's resolve.
- Lower render sizes (DLSS quality modes): render-target scaling is #3.
- GPUs other than the RTX 3070; Linux.
