# Repeated flip warning overhead

The prior 1400.991-second player session produced 80161 log lines, including 78288 warning/error lines. The single `sceVideoOutSubmitFlip: flipmode = 3` warning accounted for 34279 lines. The runtime already accepts that mode and passes each flip to the normal queue.

The entry point now reports mode 3 once per runtime process, using an atomic flag for concurrent callers. Mode 1, other mode warnings, debug tracing, queue behavior, invalid-handle/index/unregistered-slot errors and queue-full errors keep their existing behavior. This removes repeated warning formatting, logger locking and output writes for this one message. No timing or presentation semantics change.

The production-entry-point fixture failed before the fix and passes afterward: eight concurrent callers submit 10000 mode-3 flips, all accepted, with exactly one warning. It also verifies the other modes and error paths. This measures warning-call reduction, not gameplay FPS. No matched Chapter 2 route has established a frame-rate improvement.

The same player log contains many SRT offset failures. Existing code can lower ordinary dynamic reads to GPU buffers after CPU flattening fails, so log counts alone cannot identify invalid resource descriptors or the cause of the slowdown. Those diagnostics remain intact; no `ReadLane` or `Phi` is guessed on the CPU.

Local verification passes all 372 Python tests with zero skips in 75.620 seconds, plus all 44 native checks and the Windows runtime build. Fresh review, hosted Linux checks and portable-package evidence follow separately.
