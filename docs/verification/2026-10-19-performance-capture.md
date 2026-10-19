# Performance recording and Chapter 2 baseline

The user reports the game is completable and identifies the current problem as **8–14 FPS from Chapter 2 onward** on the local RTX 3070 / Ryzen 5 5600X. This is the priority for measured optimization. Formal campaign/build/hardware acceptance remains separate from that report.

The last player session used native runtime `d2fa31ee1388c44009f91309ced0bf964dce7eca55b66ed23b30f74e4acb0026`, base CUSA00076 APP_VER 01.00, experimental 60 FPS timing, original framing, FSR 1 presentation and relaxed readbacks. It ended normally after 1400.991 seconds. Pipeline binaries, background/parallel warmup and preparation workers were disabled by the launch profile; this does not establish that they caused the sustained slowdown.

## Isolated recording

A separate profiling state copied the complete current savedata tree, including Profile and Playthrough00, while holding the source session lock. Prepared files and warm caches came from the same quiescent state. The player's files were not replaced. The test used corrected preview-2 runtime `88416337ff76f31c37f9d33224e29449fdd78b3ce8c87bb482e1ad3202b13382`, the same 60 FPS/original/FSR1/relaxed settings, with windowed output and mouse capture disabled for the owned test.

Computer Use was stopped by physical Escape. No further UI input was issued. The native 600-second watchdog did not terminate the process within the outer 660-second limit; the isolated test runner then stopped its own process. The recording contains 622.759 measured seconds, 59.850 guest flips/s, 59.847 render-work serials/s, p99 20.648 ms and worst 159.937 ms. The scene was not independently identified and the reported 8–14 FPS slowdown was **not reproduced**. It cannot serve as a Chapter 2 comparison or performance improvement claim.

The timing summary retains `timing_gate_passed=false` and `milestone_accepted=false`. Render-work serials need image/command validation to establish unique rendered frames. A GPU-utilization sample during this control was 38% at 1080 MHz; it does not classify the missing slow scene. Windows WPR CPU capture failed with `0xc5585011` (profiling policy unavailable), leaving WPR not recording. Built-in timing and wait counters remain usable without that capture permission.

Private raw logs, copied state, receipts and the CSV are under `out/order1886-evidence/performance/20261019T032911Z`. They are excluded from Git/release payloads. The user was asked to load the slow Chapter 2 scene in an isolated profiling session; manual evidence is pending.

## Launcher integration

System adds **Record performance data**, off by default, with localized label/help in all 13 catalogs. Valid edits autosave and apply on the next launch. Shared settings and direct Play forward `--performance-capture`; the backend enables frame/wait diagnostics and writes a unique, exclusive CSV under the session logs. Ambient diagnostic environment overrides remain stripped. Turning recording off omits the diagnostic variables entirely because some native counters test variable presence.

Recording requires a matching hash-bound runtime receipt declaring capture support. Unsupported runtimes show a reason, reject enabling the option and preserve the previous setting. Turning an already saved option off remains possible after runtime replacement. Existing readback capability caching is shared; receipt content changes invalidate its cache even with preserved file metadata.

A deterministic replacement during capability validation also reproduced stale cached support. The worker now compares the file signature before and after validation and only caches stable results. A changed runtime returns a retry reason; enabling an unsupported option cannot persist through that stale cache.

Native trace files now use Unicode Windows paths while preserving exclusive-create protection. Failed optional recording does not throw through game startup. The receipt already records the effective diagnostic environment and now records the requested capture setting.

Six focused regressions cover settings/CLI/environment mapping, unique private trace paths, default-off isolation, unsupported-runtime rejection, saved-value preservation, disabling stale settings, replacement during validation, all 13 catalogs, Unicode file creation and preservation of existing files. Full checks pass 368 Python tests and 44 native checks before the last replacement regression; final reruns, review and package evidence remain pending. This work enables measurement; it has not improved Chapter 2 FPS yet.
