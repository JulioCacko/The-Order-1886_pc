# Windows GPU command-thread CPU diagnostics

Following performance-recording preview 3, Windows submission diagnostics now sample the current command thread with `GetThreadTimes`. Previously only Linux collected user/kernel CPU totals after each graphics submission, so Windows frame statistics reported zero CPU microseconds per draw even while the thread was working. The existing separate stall total used a Windows thread handle and was unaffected.

The collection remains inside the existing opt-in performance-statistics guard. Windows preemption/wait and GPU-thread/process page-fault counts are explicitly labeled unavailable; they are not inferred from zero counters. Linux retains its `getrusage` measurements. No launch settings, protocol, cache, save files or default rendering behavior change.

A regression extracts the production submission block, performs actual CPU work, and verifies that cumulative CPU time advances and submission counting remains intact. It failed on Windows before the fix with `after > before` false, then passed. The focused test uses the real platform API, without fabricated CPU samples. The full Windows native build and all 44 native checks pass. Full Python and hosted Linux checks are recorded after completion below.

This improves diagnostics for the reported Chapter 2 slowdown, not gameplay speed. The Chapter 2 route at 8–14 FPS remains unmeasured; no performance, gameplay or Gold gate is passed by this change. Preview 3 predates this follow-up. No UI automation resumed after physical Escape.
