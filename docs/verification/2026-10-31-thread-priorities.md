# Thread priorities and CPU use on 6 and 4 hardware threads (#134)

Issue #134: 80-100% CPU and stutter on an i5-8400 (6 cores, 6 threads, no SMT). This records
what the CPU goes to (the game's Task Kernel threads spin-waiting for jobs), the runtime change
that more than halves it (a sleep in long guest yield streaks), the priority changes that did
not help, and the one that was dropped because it made the game slower.

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
  its own investigation. The next section does that.

## The Task Kernel wait loop and the yield backoff

A temporary histogram of `scePthreadYield`/`sched_yield` return addresses (one 6-thread run)
put 24,187,234 yields at one site, guest `0x8a73a8`, and 6,869 at `0x44e935`. The site is in
the game's backoff callback at `0x8a7380`:

```
if (*count >= 1801 && pthread_self() != main_thread) { scePthreadYield(); *count = 0; }
```

The job system is set up at `0x8a1c78` (`0x20b860(kernel, 10000, 1000, 10000, 5000, ...,
callback=0x8a7380)`); each worker keeps the callback at `+0x1a8`. Five wait loops (`0x20e3d0`,
`0x20e700`, `0x20ef10`, `0x20fa90`, `0x20fc80`) wait for a job group the same way:

```
while (group->pending) {
    if (run_one_job(worker)) { count = 0; continue; }   /* 0x20a950 */
    ++count; worker->backoff(&count);
}
```

Nothing blocks: a waiting thread scans the empty queues 1801 times (about 40 us), yields, and
scans again. The runtime now notices that pattern in its yield: a thread that yields again
within 200 us of its last yield found no work in between, and from the 64th such yield in a
row (about 2.5 ms of waiting) it sleeps instead (`runtime_thread_yield`). Waits shorter than
that are unchanged, and a thread that runs a job resets the streak by its next yield coming
later. The exit report counts the sleeps and their measured length.

Windows ended each sleep after 540 to 650 us on average, whatever shorter time was asked
(100 us or 50 us). With a streak of 16 (0.7 ms) that wake-up delay cost frame rate at 6
threads; with 64 it did not in the one clean back-to-back pair.

| Run | Mask | Streak | CPU % | Task Kernel s | FPS | p50 / p95 / p99 ms | Yields (slept) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| before (pair) | 0x555 | - | 70.4 | 325.2 | 29.8 | 33.3 / 34.4 / 35.0 | 26.6 M |
| backoff (pair) | 0x555 | 64 | **27.6** | **71.2** | 29.6 | 33.3 / 33.9 / 35.8 | 4.1 M (1.38 M) |
| backoff | 0x555 | 64 | 39.6 | 95.8 | 26.6 | 33.4 / 66.8 / 74.1 | 3.5 M (0.88 M) |
| backoff | 0x555 | 64 | 24.0 | 71.0 | 22.8 | 33.5 / 102.7 / 175.6 | 3.6 M (1.05 M) |
| backoff | 0x555 | 256 | 33.5 | 123.6 | 23.1 | 33.4 / 98.4 / 200.7 | 8.7 M (0.47 M) |
| backoff | 0x555 | 256 | 36.5 | 129.6 | 29.4 | 33.3 / 34.0 / 66.6 | 9.1 M (0.85 M) |
| backoff | 0x555 | 16 | 34.1 | 71.0 | 26.9 | 33.4 / 66.8 / 95.6 | 2.3 M (1.11 M) |
| backoff | 0x555 | 16 | 32.2 | 63.7 | 25.9 | 33.4 / 67.1 / 100.2 | 2.4 M (1.20 M) |
| backoff | 0x555 | 16 | 24.7 | 53.5 | 19.6 | 34.4 / 68.9 / 100.5 | 2.2 M (1.22 M) |
| backoff | 0x55 | 16 | 49.0 | 93.0 | **22.4** | 33.5 / 67.3 / 100.5 | 1.9 M (1.13 M) |

(Task Kernel seconds are CPU time of the four threads in the 90 s window; 6-thread runs
without the backoff measured 244 to 335 s.)

- **CPU:** the backoff runs used 24-40% of the 6 threads against 66-76% without it, and the
  Task Kernel threads a sixth to a half of their time. Yields fell from 18-41 million to 2-9
  million per session.
- **4 threads:** with a streak of 16 the frame rate doubled, 22.4 FPS against 9.5-11.0 without
  the backoff; the cores the waiters gave up went to the threads doing the frame's work. The
  committed streak of 64 was not run at 4 threads.
- **Frame times at 6 threads:** not settled. The runs without the backoff gave 27.3-29.8 FPS,
  the streak-64 runs 22.8-29.6. Two runs were measured while another session's runtime was
  running and are left out (one before, one streak-64 at 50 us). Background tools outside the
  game used about a third of the 12 threads during this series (a local proxy at 35%), which
  explains part of the spread but not which way it falls. Eight more back-to-back pairs were
  started and stopped after the first.

## Not covered

- No i5-8400. The 5600X under a mask has faster cores and its own cache; the 6-thread runs show
  idle headroom the reported CPU does not have, and the 4-thread runs stand in for scarcity.
- One loaded scene with the player idle; no combat or streaming-heavy route.
- Single or paired runs per row; differences inside the noise above are not claims.
- Linux: the backoff sleeps with `nanosleep`, which ends near the asked 100 us; not run there.
