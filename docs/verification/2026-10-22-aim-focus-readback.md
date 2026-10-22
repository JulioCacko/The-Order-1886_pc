# Aim focus: the whole view blurred while aiming

Reported in gameplay: aiming blurs everything, including the target under the reticle. On the
PS4 the aimed target and most of the room stay sharp (reference screenshots supplied by the
player).

## Cause

The game keeps its aim focus on the CPU. Each frame, compute shader `0xb3d87c7f` samples the
half-size depth and writes the focus input into one of three rotating 8-byte buffers. The CPU
reads one of them back and sets the depth-of-field constants for later frames.

Under the default **relaxed** readback policy, CPU reads of GPU-written memory are not
synchronised, so the CPU kept seeing stale focus data. The result is depth of field focused at
the wrong distance, and the whole view out of focus while aiming.

## Evidence

RTX 3070, the same aim (R held for 16 s) from a copied save, screenshot at 118 s:

| Readback policy | Aimed view | FPS |
| --- | --- | ---: |
| Relaxed (default) | Whole view blurred, including the figure under the reticle | 51.4 |
| Precise (`ORDER1886_READBACKS=2`) | Sharp, as on the PS4 | 40.4 |
| Relaxed, deferred buffer readbacks off | Blurred | 42.1 |

Precise fixes the focus but synchronises every GPU-written page the CPU touches, at about
11 FPS.

`ORDER1886_READBACK_LOG=1` (new) logs each CPU readback and the compute shader that last wrote
the buffer. Under the selective policy, the only buffers the game read back were these:

```
Readback: CPU read 0x106ee88000 +8 image=0 buffer=1 writer cs 00000000b3d87c7f
Readback: CPU read 0x106ee98000 +8 image=0 buffer=1 writer cs 00000000b3d87c7f
Readback: CPU read 0x106eea8000 +8 image=0 buffer=1 writer cs 00000000b3d87c7f
```

## Fix

Under the relaxed policy, the small output buffers of the compute shaders in a short allowlist
(default `b3d87c7f`; `ORDER1886_READBACK_SHADERS` replaces it) are watched like the selective
policy watches all small outputs. A CPU read of one fetches it from the GPU, and every other
GPU-written page stays relaxed.

With the fix, the readback log under the relaxed policy shows the same three buffers read back
and nothing else. The visual check in the aiming scene is pending: the save's Continue load
landed in a different scene on each test run, so the harness could not repeat the exact aim.

## Not covered

- The exact frame-time cost of the per-frame 8-byte readbacks in combat. The game reads the
  buffers triple-buffered, so it waits for a frame that is already old.
- Other CPU readbacks in the game that may need the same treatment. `ORDER1886_READBACK_LOG=1`
  under the selective policy lists them.
