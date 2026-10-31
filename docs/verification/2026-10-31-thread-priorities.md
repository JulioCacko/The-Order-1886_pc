# Thread priorities and CPU use on 6 and 4 hardware threads (#134)

Issue #134: 80-100% CPU and stutter on an i5-8400 (6 cores, 6 threads, no SMT). This records
what the CPU goes to, what the runtime changes did to it, and the one change that was dropped
because it made the game slower.

## Setup

- Ryzen 5 5600X (6 cores, 12 threads), RTX 3070, Windows 11.
- The runtime started under `start /affinity 555` (one thread per core: 6 cores, 6 threads,
  like the i5-8400) or `start /affinity 55` (4 cores, 4 threads). The affinity is inherited by
  the probe and the runtime; every sample below confirms the mask in the running process.
- 01.02 (CUSA00076), Continue from a copy of a playthrough save, the same warm GPU cache copied
  into every run, 30 FPS engine rate, vsync off, `ORDER1886_AUDIO_STATS=1`.
- `tools/order1886_step1_evidence.py --only baseline`. A sampler read every thread's CPU time
  (`GetThreadTimes`) 150 s and 240 s after the runtime started, with the player standing in the
  loaded scene, then closed the window at 245 s so the runtime wrote its exit report. Frame
  times are the runtime's frame trace from 150 s on.
- Runtimes, all from this branch:
  - **before**: v0.2.5 plus only the new CPU report and thread names.
  - **after (first cut)**: every change, including "Task Kernel" threads below normal.
  - **final**: every change except the "Task Kernel" lowering (what is committed).

## Where the CPU goes (before, 6 threads)

In the 90 s window the process used 355 s of CPU, 66% of the 6 threads. The four "Task Kernel"
threads used 244 s of it (69%), about 65% of one thread each. The GPU command thread used 68 s
(75% of one thread), `main` 25 s. Over the whole 245 s session the game called `sched_yield`
or `scePthreadYield` 18.7 million times (about 76,000 a second); zero-length sleeps: none.
The window figures come from the sampler, the yield count from the new exit report
(`Runtime: yields`); its whole-session thread list (`Runtime: CPU time by thread`) ranks the
same five threads first.

On this CPU 6 threads leave about a third idle, so nothing waits for a core. An i5-8400 has
lower per-core speed and no idle third: the same work there is the reported 80-100%.

## Results

| Run | Mask | CPU % of mask | Task Kernel share | GPU thread s | FPS | p50 ms | p95 ms | p99 ms | Audio max gap ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| before 1 | 0x555 | 65.7 | 68.7% | 67.8 | 27.6 | 33.5 | 63.8 | 73.4 | (stats off) |
| before 2 | 0x555 | 72.8 | 76.6% | 58.0 | 29.1 | 33.4 | 35.2 | 67.0 | 51.4 |
| after (first cut) 1 | 0x555 | 66.3 | 68.6% | 68.1 | 28.0 | 33.4 | 60.1 | 75.8 | 53.5 |
| after (first cut) 2 | 0x555 | 65.4 | 69.2% | 64.7 | 27.3 | 33.4 | 66.4 | 99.6 | 46.0 |
| final | 0x555 | 75.6 | 82.0% | 35.1 | 28.9 | 33.4 | 34.5 | 67.3 | 42.2 |
| before 1 | 0x55 | 91.8 | 75.6% | 17.0 | 9.5 | 99.9 | 200.0 | 234.2 | 305.9 |
| before 2 | 0x55 | 95.1 | 74.8% | 19.2 | 11.0 | 98.8 | 167.2 | 233.2 | 52.6 |
| final (no lowering) | 0x55 | 94.9 | 74.9% | 16.2 | 10.6 | 99.3 | 167.4 | 233.5 | 53.5 |
| after (first cut) | 0x55 | 94.3 | 73.9% | 7.3 | **4.6** | 168.5 | 500.8 | 766.8 | 22.6 |

Audio "max gap" is the largest gap between output buffers in the window's last 18 five-second
reports. Every run with audio stats counted one starved buffer in the whole session (at start)
and none in the window; the 306 ms of "before 1" at 4 threads did not repeat in "before 2". The
p95 of the 6-thread runs moves between 35 and 66 ms from run to run with the same runtime, so
no frame-time difference below that is meaningful here. One more "final" run at 6 threads is
left out: its menu taps missed Continue and it measured another scene.

## What this shows

- **"Task Kernel" below normal is wrong for this game.** SpartanPort (4b843a7dd1) lowers its
  job workers, whose queue spinlock wastes cores. Here the same change halved the frame rate on
  4 threads (10.6 and 9.5-11.0 FPS without it, 4.6 with it), the GPU command thread got less than
  half its CPU time and `main` more: the Task Kernel threads run the game's jobs, and the threads
  waiting for those jobs wait longer. It is not committed.
- **The other changes show no measured gain on this machine.** Above-normal priority for the
  AK:: sound threads, normal instead of above-normal shader capture threads, and the bounded
  backoff in the GPU waits left frame rate, frame times and audio gaps inside run-to-run noise,
  at 6 and 4 threads. Total CPU did not drop: 75.6% in the final 6-thread run against 65.7% and
  72.8% before. In that run the GPU command thread used 35 s against 58-68 s in every other
  6-thread run, and the Task Kernel threads took the difference; one run, so the cause (the
  backoff, or the scene's timing) is not established.
- **CPU use itself is the Task Kernel threads polling.** About 2.7 cores of yield loops, 18 to
  41 million yields per 245 s session. No priority change reduces that: the threads take every
  cycle nothing else wants, so freeing a core elsewhere only moves it to them. Lowering it
  means making the idle polling block (the guest loop at `0x20a950`/`0x8a7380`), which needs
  its own investigation.

## Not covered

- No i5-8400. The 5600X under a mask has faster cores and its own cache; the 6-thread runs show
  idle headroom the reported CPU does not have, and the 4-thread runs stand in for scarcity.
- One loaded scene with the player idle; no combat or streaming-heavy route.
- Single or paired runs per row; differences inside the noise above are not claims.
