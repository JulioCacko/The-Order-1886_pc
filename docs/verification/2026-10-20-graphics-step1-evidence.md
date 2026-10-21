# Graphics step 1: in-game evidence for the newly wired options

Branch `graphics/step1-cheap-wiring` (base `0dc552f`). Runtime SHA256
`e3dc2081bd8a92c43ab752352967883e2557d97d19cb0540bafaf3df424eb24a`, RTX 3070 (driver 617.14),
Windows 11, base game CUSA00076 APP_VER 01.00. Captured on 20 October 2026.

## Method

`tools/order1886_step1_evidence.py` runs `tools/order1886_graphics_probe.py` once per variant.
Every run uses the same steps:

- an isolated state with no player files and a new cold GPU cache;
- the 60 FPS profile in a window;
- Space (Cross) pressed 45 s after launch, which opens the title menu;
- frame dumps and a desktop screenshot at 52 s and 58 s;
- the native frame trace, with the row cut off by the 62 s timeout dropped.

The first run is the launcher defaults. A second run with the same defaults measures run-to-run
noise: its output frames differ from the first by a mean of 0.057/255 (PSNR 60.6 dB). A
difference counts only above that.

The warm-up variants need cached pipelines, so they ran again from a copy of the first run's
cache (116 pipelines). Each of those runs has its own warm baseline.

Raw dumps, logs, traces and full screenshots are in `out/order1886-evidence/step1/`, which Git
does not track. The full screenshots show the whole desktop. Only the cropped game-window images
below are committed.

## Results

| Option | Runtime log line | Measured effect | Verdict |
| --- | --- | --- | --- |
| Output resolution | `output 1280x720` / `output 2560x1440` | Output frames dumped at 1280×720 and 2560×1440; the default dumps at 1920×1080 | Works |
| Sharpening 100 | `sharpening on (100)` | Output differs from defaults by 0.232/255 mean, PSNR 44.3 dB (noise: 0.057, 60.6 dB). The guest image is unchanged (0.056). | Works |
| Overlay items | `overlay items 0x1` / `0x7b` | Frame time, GPU, CPU, RAM and VRAM lines appear only when on (image below) | Works |
| Frame cap 45 (in-game menu on) | — | 44.37 FPS, p50 22.25 ms; default cap: 58.77 FPS, 16.61 ms | Works |
| Deferred image readbacks | `deferred image readback enabled` (default: `disabled`) | No frame-time change on the title menu | Consumed; effect needs gameplay |
| Frames queued 0 / 2 | `frames queued 0` / `2` | No frame-time change on the title menu (VSync Fifo). Latency was not measured. | Consumed; effect not measured |
| Async shaders | `async shaders 1` | Cold cache: worst frame 209 ms against 455 ms (one run each). Warm cache: no change. | Consumed; cold-start stall smaller in one run |
| Background warm-up | `Pipeline warm-up: loading in the background (6 threads)`; 94 of 116 in 2.04 s | Default warms all 116 before the first frame (2.43 s). Background: 3604 guest flips in the window against 3445–3472, worst frame 157 ms against 63 ms | Consumed; earlier first frame, one longer hitch |
| Parallel warm-up | `116 of 116 pipelines in 1.48 s (6 threads)` (default 2.43 s, 0 threads) | Warm-up 39% faster, but p99 33.1 ms and 25 frames over 33 ms against 20.5–21.4 ms and 9–11 | Consumed; worse frame pacing in this run, keep unqualified |
| Anisotropy 16× | `anisotropy 16` | Title menu has no oblique 3D surfaces: no difference (0.057) | Consumed; visual effect not shown |

![Overlay items off and on](../images/order1886-overlay-items-20261020.jpg)

![Sharpening off (top) and 100 (bottom), output frame, 2× zoom](../images/order1886-sharpening-20261020.png)

## What blocked the gameplay scene

The plan was to load the player's latest save with Continue and measure anisotropy and the
frame-time options in gameplay. At that save, both this runtime and a runtime built from base
`0dc552f` without the step-1 changes (SHA256 `2ef61708…`) show a flat sky-blue frame for over two
minutes. Pixel spread in the centre is under 1/255, and the only feature is the "Once a Knight"
chapter title. The release runtime from `54242e0` (SHA256 `ca77edaf…`) shows the cell cutscene at
the same save and timings. The regression is in one of the GPU commits between `54242e0` and
`0dc552f`, not in step 1. A separate bisect is proposed.

## Still open

- Anisotropy and deferred readbacks need a gameplay capture after the regression is fixed.
- Frames queued needs an input-latency measurement; frame time alone cannot show it.
- Each warm-up and async result comes from a single run. Repeat runs are needed before any of
  them loses the "unqualified" label.
