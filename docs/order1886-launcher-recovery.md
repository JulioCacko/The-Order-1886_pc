# Launcher output, performance overlay and Git recovery

16 October 2026. The reported Python traceback is fixed independently of native game compatibility.

## Reporting failure

The user's latest old-package run was
`dist/order1886/20261016T061117Z-917a09caa583/The Order 1886/user/order1886/logs/20261016T101004.041653Z-boot.json`.
It recorded native exit 0 after 228.692 seconds, without a timeout, requested/forced stop or fatal reason. Its last native log write was after approximately 47.5 seconds. The screenshot shows the original saving notice; the log does not establish why the process exited or prove save I/O deadlock. It contains SRT/Phi errors, but no save API call trace or FMask assertion.

The traceback occurs when `order1886.main` prints its final result and then attempts to print the reporting exception to stderr. Invalid standard streams can fail twice, replacing the visible result with a Python traceback. Exact late errno 22 reproductions cover native exits 0 and 23. A separate live FreeConsole test demonstrates invalidated console handles (errno 9 / WinError 6), without claiming that FreeConsole triggered the user's particular run.

The launcher now redirects backend output into its real session log and tails that file into the UI. Recovered Windows handles are duplicated before wrapping them, retaining independent ownership even when stdout/stderr share the original handle. Backend status output falls back to durable logs if a stream is absent or invalid. Native exit codes and run metadata remain authoritative.

Tests cover success and failure exit preservation, late output failure, startup cleanup, shared/borrowed HANDLE ownership, UTF-8 session-file relay, and absent standard streams in a hidden windowed backend. Evidence: `out/order1886-evidence/stdio-regressions/stdio-fix-note.md`, `before-native0-and23.log`, `after-real-console.json`, and `freeze.json`.

## Performance overlay

The native panel is titled The Order: 1886 and labels its rates as presentation metrics. Fresh launcher settings enable it; an explicit saved off preference remains respected. Settings exposes **Performance overlay (F9)**. F9 hides/shows it for the current session, independently of the disabled native settings menu.

Default fields are successful presentation FPS, present interval, process CPU and process RAM. Existing explicit GPU selections remain supported; unavailable metrics show n/a. Sampling continues while the panel is hidden, counts long intervals and keeps loading-screen samples separate. These are host presentation statistics, not proof of distinct guest frames or gameplay performance.

Live Windows capture verified the panel during the original intro at the standard 30-present/s cap (approximately 29.9 presentations/s and 33.4 ms at the captured instant). A separate UI-only run deliberately used a 5-present/s cap to keep the window available for input verification. F9 hide and restore were visually confirmed, followed by normal window closure and native exit 0 after 36.625 seconds. That test is not a performance benchmark; the cap override exists only in ignored `out/order1886-evidence/overlay-ui-repro.py`. Shipped settings retain 30.

The isolated UI run's metadata is `out/order1886-evidence/save-notice-repro-user/logs/20261016T103913.591464Z-boot.json`. Standard-cap diagnostic attempts on a copied user folder still encountered unsupported FMask selectors and exited 23. This work does not establish menu, gameplay, save/load or stability.

## Build and checks

- Runtime SHA256: `ca415f6aae4c0c77003f16defecfceecc6f5f206a7fac2febf6ab0a579f149df`.
- Receipt revision: `7e16a1d13188ee1bcde4edfc4a59df0317630e92`, dirty source. Source digest: `e954e9aa557d156d62c01cd13eee23b22ab530f7822c40381ed9738018430003`.
- Eight native checks pass: `out/order1886-evidence/overlay-stdio-final-build.log`.
- Python suite: 149 tests, 138 passed, 11 skipped; `out/order1886-evidence/overlay-stdio-python-tests.log`. Skips require absent standalone native test executables.
- Overlay CPU regression and exact native caller syntax checks pass. Full `git diff --check` passes.

Fresh package directory: `dist/order1886/20261016T103900Z-ca415f6aae4c/The Order 1886`; archive: adjacent `order1886-windows.zip`. Portable validation now includes an additional hidden, null-stdio backend gate. Final package delivery hashes and results are recorded separately after the gate completes.

## Git privacy rejection

The account's verified GitHub identity is JulioCacko, numeric ID 11414423. Repository-local email is now `11414423+JulioCacko@users.noreply.github.com`. The prior single unpublished commit was amended from `1d491a1` to `7e16a1d`, changing identity metadata while retaining the same source tree and parent. A normal push to `https://github.com/JulioCacko/The-Order-1886_pc.git` succeeded and remote main was verified at `7e16a1d`. No force push or privacy-setting change was used. The launcher/overlay fixes from this follow-up remain local working-tree changes until committed.
