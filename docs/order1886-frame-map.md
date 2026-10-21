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
| #60–#74 | Lighting and forward passes, **MSAA** | `…100000` RGBA16F 1920×800 (scene color) |
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

- **Scene color** is a multisampled texture (4× on the PS4; 2× on the host here). The shader reads every sample and weights each by
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

### Velocity validated in the runtime

`ORDER1886_TEMPORAL_PROBE=1` (`tools/order1886_graphics_probe.py --temporal-probe`) runs
`host_shaders/temporal_probe.comp` right after the game's resolve, on the same inputs. It
resolves the MSAA scene color and keeps it for the next frame. On every moving pixel whose
velocity is not saturated, it then measures how well the previous frame predicts the current one
under three assumptions: no motion, `pixel + 16·v` and `pixel − 16·v`. It logs the mean
absolute luma difference every 120 frames.

One gameplay run from the player's save, with short camera turns every 8 s (runtime SHA256
`03c4b1e4…`), produced eight 120-frame reports with moving pixels. Each report compared
36 705–189 144 pixels:

| Assumption | Mean \|ΔLuma\| across the eight reports |
| --- | --- |
| No motion | 0.058–0.147 |
| `pixel + 16·v` | 0.014–0.019 (0.147 in the first, turning-start report) |
| `pixel − 16·v` | 0.068–0.147, worse than no motion every time |

`pixel + 16·v`, the shader's own decoding, cuts the error four to five times. The convention is
therefore what the shader shows: the previous position of a pixel is `pixel + 16 · v`, with `v`
decoded as above. The earlier offline mismatch came from comparing against the game's history
image, which is accumulated and jittered and is not the previous frame.

The runtime reports the scene color as `R16G16B16A16Sfloat`, 2 samples on the host. The guest
count is mapped by `video_core/amdgpu/ps4_msaa.h`. Velocity saturates (|v| ≥ 0.98, beyond
16 px) during fast camera turns at low frame rates. Those pixels carry no motion information.

A provider therefore replaces this one dispatch. Its inputs are the MSAA scene color (resolved first),
depth `…7c0000`, decoded velocity and exposure, and its output goes where `…c00000` went.

## A provider in place of the resolve

`video_core/renderer_vulkan/vk_order_resolve.cpp` does this when `runtime.ini` asks for an
upscaler (`upscaler=fsr3` or `upscaler=dlss`) and that provider loads (`vk_upscale_providers.cpp`).
The design comes from IgorAugustoHH/The-Order-1886-PC-Port (`vk_order_dlss.cpp`), moved onto the
provider ABI in `shim/order1886_upscale.h`.

1. Every draw remembers the depth target drawn with the MSAA RGBA16F scene color, and whether the
   scene's depth-writing draws test with Greater (reversed depth).
2. After the game's resolve dispatch, `host_shaders/order_resolve_prep.comp` writes the provider's
   inputs: color resolved with the game's `1 / (1 + exposure · luma)` weights (RGBA16F), velocity
   decoded as above and multiplied by constant 63 (RG16F, pixels, previous minus current), and
   depth sample 0 (R32F).
3. The provider runs at the scene size (1:1, no jitter, motion scale 1) into its own RGBA16F image,
   which is then copied over the resolve's output. That output is also the game's history, so
   motion blur, depth of field, bloom and the tonemap read the provider's result unchanged.
4. The game's resolve still runs first. If the inputs are not recognised or the provider fails,
   its result stays, and the log says why.

Camera planes and field of view are placeholders (near 0.1, infinite far, 0.7 rad) until the
game's camera constants are located.
