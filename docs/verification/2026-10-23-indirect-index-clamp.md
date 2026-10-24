# Gameplay freeze: indexed indirect draws with a runaway index count

## Symptom

During gameplay the runtime sometimes stops presenting. The process stays alive,
`ORDER1886_FRAME_TRACE` stops growing and later frame dumps never happen. This happened in 2 of 6
runs on 2026-10-22 (57 s with NVIDIA DLAA, 81 s with no upscaler).

## Where it hangs

- The GPU command thread waits in `Scheduler::Wait`, called from `Presenter::PrepareFrame` (the
  frames-ahead wait). The draw recording thread and the present threads are idle.
- The GPU is busy, not waiting: nvidia-smi showed 100 %, 1.9 GHz and 110-145 W, and no TDR was
  logged. The timeline semaphore stops one tick before a submission that waits on nothing.
- A per-command GPU timestamp ring (diagnostic build, not part of this change) found the command
  that never ends: an indexed indirect draw (`max_count` 1, no count buffer). Its arguments, copied
  on the GPU right before the draw, were `[4294967290, 610, 0, 0, ...]`. That is an index count
  of -6 with 610 instances. Other freezes showed 26, 40, 67 and 17 instances.

## Who writes the count

The game builds these arguments on the GPU. Compute shader `cbe2016a` writes 16-byte records:
`indexCount = (in0[i*255+196] & 0xFFFF) * 3 - 6` and `instanceCount = in1[i]`. `in0` is a
CPU-written, double-buffered record array. `in1` is a per-record count that shader `47ecaafb`
keeps across frames, clearing it only when record word 2 is -1. A record with count 0 and a valid
word 2 therefore produces `0xFFFFFFFA` indices with the instances of earlier frames. That never
appears in normal frames.

Ruled out by diagnostics on the stored chapter 2 save:

- The GPU's copy of the `in0` count fields equals guest memory at the args builder's bind: 0
  differences across 6 stressed runs, 3 of which produced -6 counts. Not a stale upload.
- `47ecaafb` and `cbe2016a` always bind the same `in0` half, and record words 2 and 196 do not
  change between their binds (4 runs, all with -6 counts). The guest itself wrote these records.
- Not caused by the draw pipe, deferred uploads, deferred readbacks, missing barriers
  (`ORDER1886_FULL_BARRIERS=1`), or `WaitHostCopies` ordering of DmaData host writes: each still
  froze with the feature turned off or the wait added.
- Selective readbacks (`ORDER1886_READBACKS=3`) do not prevent it either: 2 of 10 stressed runs
  froze.

Why the game writes such records is still open. The freeze needs the emulator to lag the guest
(about half of the stressed runs; 0 of 11 runs at ~49 FPS without load).

## Fix

GCN bounds an indexed draw's fetches by `INDEX_BUFFER_SIZE`: indices past it read as 0, which makes
degenerate primitives that draw nothing. Vulkan has no such bound, so the GPU processed all
4.3 billion indices for every instance. Before each indexed indirect draw, the runtime now copies
the records into a small ring and clamps each index count to the indices the bound index buffer
holds after `firstIndex` (`host_shaders/indirect_index_clamp.comp`,
`Rasterizer::ClampIndexedIndirect`). The visible output is the hardware's: the same primitives
up to the end of the buffer. In the freezing scene the bound index buffers hold 54, 120 and 3828
indices, so a bad record now costs microseconds.

The clamp is skipped when no `INDEX_BUFFER_SIZE` was set (`max_index_size` 0), so the bound is
unknown. Disabled-optimization bit `1 << 56` (`IndirectIndexClamp`) turns it off for A/B runs.

## Same path, wrong geometry

When a bad record has few instances, the draw finished after a few seconds and rendered whatever
the shaders made of out-of-range indices: candidates for the reported giant flat triangles. With
the clamp, the draw covers the bound mesh only. The mesh can still appear for a frame with stale
instance data, because the clamp bounds the draw but does not repair the record.

## Evidence

Stored chapter 2 save (copied, `--continue-save 45`), 12 High-priority CPU spinners started 90 s
into each 200 s run. Same build, interleaved:

| Clamp | Runs | Stopped presenting | Longest present gap |
|---|---|---|---|
| on | 10 consecutive | 0 | 15.0 s (CPU stress; frames resume) |
| off (bit 56) | 4 | 1 (at 91 s) | 30.1 s in another run |

All runs show 2-15 s present gaps once the spinners start, with or without the clamp.

Selective readbacks were considered as the default and rejected. With this clamp in the build,
`ORDER1886_READBACKS=3` still stopped presenting in 2 of 10 stressed runs (at 113 s and 142 s).
An unstressed run stalled 72 s, with the GPU command thread in a read fault:
`ReadMemory` → `DownloadMemory` → `Scheduler::Finish`. Unstressed chapter 2 ran at 45.8 and
31.8 FPS with Selective, against 58.7 and 57.0 with Relaxed. Unstressed
chapter 2 with the clamp: 58 FPS. `bash build.sh --test`: 56 native checks pass.
`tests/test_order1886_indirect_index_clamp.py` compiles the shader with glslang and checks that
indexed indirect draws read the clamped arguments.
