# The Order: 1886 frame map (temporal inputs, #7)

This page records where a temporal upscaler finds each input it needs in The Order's own frame. It
is based on gameplay frame captures (`tools/order1886_graphics_probe.py --frame-capture`, through
`tools/order1886_step1_evidence.py`) and on the decompiled shaders (`--dump-shaders`, then
`spirv-cross`). Addresses are the lower bits of the guest addresses in one session. They identify
targets within a capture and are not stable identifiers. Shader hashes are stable.

## The frame, in order

Scene rendering is 1920×800, letterboxed into a 1920×1080 display buffer at the end. A gameplay
frame has about 125 passes and dispatches.

| Passes | Work | Targets |
| --- | --- | --- |
| #0–#2 | G-buffer | `…538000` A2B10G10R10 velocity, `…e00000` A2B10G10R10, `…020000` R16Uint, depth `…7c0000` D32 |
| #4–#21 | Depth copies, tiled light lists (120×50), SSAO-style passes | `…358000` / `…508000` / `…c30000` D32 copies, `…838000` RG8 |
| #27–#59 | Shadow maps and their filtering | D32 512×512, RGBA16F 1024×1024 / 512×512 |
| #60–#74 | Lighting and forward passes, **4× MSAA** | `…100000` RGBA16F 1920×800 (scene color) |
| #75 | **The game's temporal resolve** (cs `92311aca`) | reads exposure, velocity, MSAA scene color and history `…b60000`; writes `…c00000` |
| #82–#88 | Motion blur (velocity tile max down to 60×25, then the blur) | output back into `…100000` |
| #89–#96 | Depth of field at half resolution | output `…450000` RGBA16F |
| #97–#99 | Luminance down to 1×1 | exposure `…cc0000` R32F |
| #100–#120 | Bloom chain (B10G11R11) | |
| #121 | Tonemap and composite | `…c28000` RGBA8 sRGB |
| #122 | Copy | `…0f8000` A2B10G10R10, read again by the next frame |
| #124 | Letterbox into the display buffer | `…c08000` RGBA8 1920×1080 |

## The game's temporal resolve (#75)

From the decompiled shader `cs_0x0000000092311aca`:

- **Scene color** is a 4× MSAA texture. The shader reads every sample and weights each by
  `1 / (1 + exposure · luma)`, a tonemap-weighted resolve.
- **Exposure** is `exp2` of the first texel of `…cc0000`. When a flag in the constants is 0,
  a constant from the constant buffer is used instead.
- **Velocity** (`…538000`, A2B10G10R10): R and G hold magnitudes and the 2-bit alpha holds the
  signs. `vx = -R · (A&1 ? -1 : 1)`, `vy = G · (A&2 ? 1 : -1)`. The history position is
  `pixel_center + scale · v`, divided by the render width and height. `scale`, width and height
  come from the constant buffer (`data[63]`, `data[64]`, `data[65]`).
- **History** (`…b60000`, RGBA16F) is sampled bilinearly at that position. The result is written
  to `…c00000`.

Constants recorded with the dispatch in every gameplay capture:

| Index | Value | Meaning |
| --- | --- | --- |
| 60 | 5 | Exposure used when the exposure texture is not read |
| 61 | 1 | Read exposure from `…cc0000` |
| 62 | 0.5 | Not identified |
| 63 | 16 | Velocity scale: one unit is 16 pixels |
| 64, 65 | 1920, 800 | Render width and height |

### What is not yet validated

The velocity sign and scale have not been confirmed against motion in the image, for two
reasons:

- At about 7 FPS in this courtyard, a keyboard camera turn moves more than 240 px per frame.
  The velocity target saturates (median |vx| 0.999), so it carries no scale information.
- On the pixels that are not saturated, sampling history at `pixel − k·v` fits better than
  `pixel + k·v`. That is the opposite of the sign read from the shader, so one of the two
  readings is wrong.

History is also not simply the previous frame under a still camera. In a capture with no camera
motion (vx ≈ 0), history and the current color still differ by more than a 40 px shift. A
scripted relative mouse drag did not turn the camera in that run.

The next check is to reproject in the runtime itself, by running a provider at 1:1 on these
inputs and comparing motion with and without each sign. Comparing offline dumps is limited by
the frame rate and by how the capture serialises passes.

A provider therefore replaces this one dispatch. Its inputs are the MSAA scene color (resolved first),
depth `…7c0000`, decoded velocity and exposure, and its output goes where `…c00000` went.
