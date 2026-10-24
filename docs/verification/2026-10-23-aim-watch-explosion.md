# Exploding cloth and skinned geometry from the aim-focus readback

Reported after the v0.2.0 release build: large flat triangles across the screen in the chapter II
"Evidence" cutscene (Council of Knights). The release was held.

## Cause

Pull request #100 made the relaxed readback policy watch the output buffers of compute shader
`0xb3d87c7f` (the aim autofocus). A CPU read of one faults, and the fault handler fetched the
buffer from the GPU: it queued the download on the GPU thread, which called `scheduler.Finish()`
in the middle of the frame, and waited for it. The game reads these buffers three times a frame.

A RenderDoc capture of an exploding frame (watch on, frame 8003) shows the broken draws: four
consecutive draws of one mesh (vertex shader 73562) whose vertices land up to 3,900 screen widths
away. Their vertex buffer holds a flat grid (every `y` is 1e-6), the rest shape of a cloth mesh.
No dispatch and no upload copy in the frame writes that range: the simulated vertices the CPU
wrote never reached the GPU copy.

What decided it, on the main build (`4c9c20f`, index clamp included), all with the watch on:

| Variant of the watched read | Exploding geometry |
| --- | --- |
| Download the 512 KB window and wait (main) | yes, every run |
| Write-fault window off (`ORDER1886_TOGGLE_FILE` bit 65536) | yes |
| Deferred readbacks off (bit 2^58) | yes, fewer |
| Download the page without waiting for it | yes, more |
| Download only the 8 bytes read, and wait | yes |
| End the watch, download nothing | no |
| Copy the 8 bytes without `Finish()`, publish when the GPU is done (this change) | no |

The 8 bytes are plain values (`1.0`, later about `0.728`, never NaN) and usually equal what the
guest already held, so the data itself is not the trigger. The mid-frame `Finish()` is: with it,
cloth and skinned vertices go stale in the cutscene; without it, they do not. Which pipelined path
loses the CPU-written vertices across that submission is not yet known; other paths that call
`Finish()` mid-frame may show the same corruption.

## Fix

A watched read under the relaxed policy no longer waits. The fault handler ends the watch on that
page and returns, so the read sees the value published by the previous read. The GPU thread
records a copy of only the bytes read into staging memory, and a deferred operation writes them to
guest memory when the GPU has finished that work. No `Finish()`, and no other byte of the page is
written back. The game reads the buffers triple-buffered, so a value one frame older is what it
expects.

`ORDER1886_READBACK_SHADERS` keeps its default (`b3d87c7f`), so the aim-focus fix from #100 stays
on.

## Evidence

RTX 3070, chapter select into chapter II, 30 window shots 5 s apart, a fresh copy of the save on
every run, `ORDER1886_READBACK_SHADERS=b3d87c7f`:

| Run | Build | Exploding geometry | Freezes over 5 s |
| --- | --- | --- | ---: |
| mainwatch-101703 | main `4c9c20f` | shots 11, 19, 23, 28 | 0 |
| rdwatch-102507 (RenderDoc) | main `4c9c20f` | shots 11, 16, 17 | 0 |
| abfw-103825 | main, write-fault window off | shots 1, 9, 13, 17, 18, 28 | 0 |
| exact-110956 | 8-byte download with `Finish()` | shots 5, 10, 11, 21, 24 | 0 |
| mainoff-101158 | main, watch off | none | 0 |
| publish-112008 | this change | none (30 shots) | 0 |
| publish2-112709 | this change | none (30 shots, into gameplay) | 0 |

`ORDER1886_READBACK_LOG=1` shows the same three 8-byte buffers read back as in the #100 evidence.
`bash build.sh --test` passes (56 native checks).

The smoke grenade in chapter I hits the same bug, since throwing aims. On the main build plus the
smoke-cloud fix, with the watch on, one run drew the smoke in rainbow colors and another drew
stretched planes across the screen. In a RenderDoc capture of the second (frame 3364), the planes
are draw 12089, ordinary level geometry (2,208 indices), whose vertex positions are 1e35 and NaN.
The same build with `ORDER1886_READBACK_SHADERS=0` (watch off) drew grey smoke on both throws.

![Main build (left) and this change (right), same camera](../images/fixes/aim-watch-explosion-before-after.jpg)

## Not covered

- The aimed view in gameplay. The #100 visual check was never completed either (the save's
  Continue load lands in a different scene on each run). The values reach guest memory, one frame
  later than before.
- Why a mid-frame `Finish()` loses CPU-written vertex data. Image readbacks and write-fault
  downloads also call it, and may explain other intermittent broken scenes.
- Other chapters. Only the chapter II cutscene was run.
