# Slow gameplay (#3): ports from TOport and their measured gain

Branch `perf/toport-renderer`, based on `graphics/step1-cheap-wiring` (`9d951cd`, which carries the
HTILE depth-clear fix from #88). RTX 3070 (driver 617.14), Ryzen 5 5600X (12 hardware threads),
Windows 11, base game CUSA00076 APP_VER 01.00. Captured on 21 October 2026.

[TOport](https://github.com/IgorAugustoHH/The-Order-1886-PC-Port) (GPL-2.0, same shadPS4 and
Bloodborne-port lineage) reports 45–50 FPS in heavy scenes on an RTX 2060 with the game's own TAA.
Its history and this repository share commit `1d34202` (7 October 2026); TOport has 139 commits
after it. Three of them explain the gap. They are ported below, one at a time, with a frame-time
capture before and after each.

## Method

`tools/order1886_step1_evidence.py --only baseline baseline-repeat` with a copy of the player's
savedata, `--keys 45:space 53:space`, `--delays 150 170 190`, `--timeout 200` and
`--measure-after 100`. Each run starts from a new cold GPU cache and the launcher defaults
(60 FPS profile, relaxed readbacks). Frame times count from 100 s into the native trace, about 98 s
of gameplay per run. The new `--env KEY=VALUE` option passes `ORDER1886_FRAME_STATS=1`, which the
launcher environment would otherwise strip. GPU clock and load come from
`nvidia-smi --query-gpu=utilization.gpu,clocks.gr -lms 1000`.

The keys reach the night courtyard that step 1 measured at about 7 FPS. Which scene the keys reach
depends on menu timing:

- With `--delays 150 190` the same keys loaded a day alley (17.4 FPS, 857 draws per frame) instead.
- In 2 of 11 runs the Continue tap at 53 s was missed and the run stayed on the title menu (213 draws
  per frame, 60 FPS). Those runs are not counted.

Each run's frame was checked to be the courtyard (about 1526 draws per frame) before its numbers were
used.

## Diagnosis

At about 7 FPS the GPU ran at 210–315 MHz and 33% load (average 297 MHz while the courtyard was on
screen). The driver kept it at idle clocks because it had little work: the bottleneck was on the CPU.
The frame stats showed the GPU command thread never idle (`idle 0.0%`) at 44–47 µs per draw.

Windows thread times are too coarse to say where that time went (15.6 ms ticks), and WPR is not
available on this machine (see the 19 October capture note). Instead, `lldb` attached to the
running game and stopped it at random intervals 80–120 times, recording every thread's stack. In the
first capture 38 of 80 samples (47%) of the GPU command thread were blocked in
`runtime_memory_clamp` → `pthread_rwlock_rdlock` → `WaitForSingleObjectEx`. The three guest copy
threads were blocked on the same lock in `runtime_memory_read_backing`. winpthread's rwlock
serializes even readers on a spin lock backed by a kernel event, so four threads that only read the
region table took turns through the kernel.

After that fix, 26 of 100 samples were in `Scheduler::Finish`. A compute `ReleaseMem` wrote its fence
label onto a page that also held GPU-written bytes. The write fault downloaded the page and waited
for the whole GPU each time.

After that fix, the profile was flat per-draw work (`DrawRecord`, `BindResources`,
`GetGraphicsPipeline`), all on the GPU command thread.

## Results

| Step | Runtime SHA256 | FPS | p50 ms | p99 ms | GPU clock |
| --- | --- | --- | --- | --- | --- |
| Baseline (`9d951cd`) | `ccc23525…` | 7.17 | 139.47 | 163.91 | 297 MHz, 33% |
| 1. SRW lock for the memory region table | `6408c0a5…` | 27.39 / 27.30 | 36.14 / 36.19 | 43.30 / 44.04 | 1211 MHz, 37% |
| 2. + deferred buffer readbacks | `cc8ef6a0…` | 35.90 / 35.91 | 27.49 / 27.69 | 35.37 / 33.21 | 1607 MHz, 37% |
| 3. + two-stage draw pipeline | `8fede3ec…` | 54.80 / 54.82 / 54.82 | 18.47 / 18.45 / 18.42 | 21.50 / 21.69 / 21.35 | — |

Two or three runs per row; all are listed. Output frames at 170 s differ from the step-2 run by a
mean of 0.33–0.55/255 (1.88 in one run whose camera ended slightly turned). Two step-1 runs differ
from each other by 0.71–0.87/255, so these differences are run-to-run noise.

### 1. SRW lock for the memory region table (TOport `a15cf8b`)

`src/runtime_memory.c` uses a Windows slim reader/writer lock instead of `pthread_rwlock_t`.
Shared acquisitions do not nest safely while a writer waits, so a per-thread `read_depth` counts
nested reads and only the outermost one locks. Other platforms keep the pthread lock.
Frame stats: 44–47 → 17 µs per draw, GPU-thread kernel time 26 → 1 ms per frame, copy threads
blocked 7.8% → 1.0%.

### 2. Deferred buffer readbacks (TOport `32efe96`, merge rules from `e03c9e9`)

A guest write fault on a GPU-modified page whose written bytes are not GPU data no longer waits for
the GPU. The GPU-written ranges of the 512 KiB window are copied to a staging buffer in the current
submission and written to guest memory once it completes, only where the guest left its bytes as
they were at the fault. Until then uploads keep those bytes in the arena, and
`IsRegionGpuModified` reports them as GPU data. Readbacks bigger than 4 MiB keep the waiting path.
Relaxed readbacks only (the launcher default): the snapshot reads guest pages that the other modes
keep read-protected. `gpu/shadps4/video_core/buffer_cache/deferred_readback_merge.h` is copied
from TOport with its GPL header. `ORDER1886_DEFER_BUFFER_READBACK=0` or toggle bit 58 turns it off.
Frame stats: time blocked on GPU ticks 26% → 0%.

Known hazard (raised in review, not fixed): CPU writes are detected only by comparing guest bytes
with the snapshot taken at the fault. If the guest writes a pending GPU byte with the same value it
had at the fault, or writes it between that comparison and the copy, the GPU data written later
replaces the CPU write. Protection works per page, and the page is unprotected so that the faulting
write can go on, so later writes to it cannot be caught. Closing this needs the GPU wait that the
change removes. No such case was seen in the runs above. `ORDER1886_DEFER_BUFFER_READBACK=0` is the
fallback if one shows up.

### 3. Two-stage draw pipeline (TOport `888c546`, `5534ce9`)

The draw pipeline (`vk_draw_pipe.h`) was already in this tree but switched off, because Vulkan
validation had found two threads writing the same command pool. TOport fixed that race after the
shared commit. The scheduler now drains the draw recording thread before `EndRendering`,
`CommandBuffer()` and `SubmitExecution`, and the presenter drains it before `PrepareFrame`.
It is on with 8 or more hardware threads, as in TOport. `ORDER1886_DRAW_PIPE=0` or `1` overrides
that, and toggle bit 37 turns it off while the game runs.
Frame stats: 17.8 → 11.7 µs per draw on the GPU command thread.

## Measured and not ported

- Draw preparation workers (`ORDER1886_PREP_WORKERS=6`, TOport's default is half the hardware
  threads): 53.24 FPS, p50 18.82 ms against 54.8 FPS without them. The frame stats also counted
  1514 draws per frame instead of 1526. The launcher keeps them off for the descriptor problem noted
  in `vk_draw_prep.cpp`. This tree keeps them off.
- TOport's compute and command pipes (`BB_COMPUTE_PIPE`, `BB_COMMAND_PIPE`): not ported. The
  profile after step 3 shows no time in the paths they move.

## Checks

- `bash build.sh --test`: 56 native checks pass. `tests/test_memory_output_publication.c` reaches
  into the region lock and now checks the SRW lock on Windows.
- `python -m unittest discover -s tests`: 514 tests, OK (19 skipped).
- Stability, step 3 runtime: one 720 s run in the courtyard ended at its timeout without a fault.
  Over 619 measured seconds: 56.07 FPS, p50 18.79 ms, p99 28.22 ms. The one long frame (5.04 s,
  about 380 s after launch) compiled 818 shaders and registered 1041 images in that frame: the
  game streamed in new content with a cold cache and synchronous compiles. The courtyard still
  rendered correctly at 600 s.

## Still open

- No Vulkan validation run: the Vulkan SDK layers are not installed on this machine.
- Only one heavy scene was measured. The day alley went from 17.4 FPS at baseline; it was not
  measured again.
- The runtime still runs below the 60 FPS cap in this scene. The GPU command thread is the limit at
  about 11.7 µs per draw and 1526 draws per frame.
- `ORDER1886_GPU_PROFILE=1` prints no report unless camera motion is on. `NoteFrameStart` is only
  called from that branch, so the profiler never closes a frame.
