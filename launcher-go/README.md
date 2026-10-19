# The Order: 1886 Go launcher preview

Wails v2.17.0, Go and locally embedded TypeScript/HTML/CSS. This is an opt-in migration preview; the existing Python launcher remains the default distribution path.

## Develop

Requires Go 1.25+, Node.js compatible with Vite 7, and Python with the existing project's preparation dependencies.

```powershell
rtk proxy npm --prefix frontend ci
rtk proxy npm --prefix frontend run build
rtk proxy go test ./...
rtk proxy go run github.com/wailsapp/wails/v2/cmd/wails@v2.17.0 build -skipbindings
rtk proxy powershell -Command '& "./build/bin/The Order 1886.exe" --project-root ".."'
```

Run from this directory. `prebuild` copies the canonical official artwork without modifying it. Source development uses the worker at `launcher/order1886_worker.py`; portable builds use `bin/order1886-worker.exe` and need no separately installed Python.

The worker owns validation and atomic settings writes. Its JSON-lines v1 allowlist supports state/settings, sessions, saves, shader cache, mods, Steam and shortcuts. Stdout carries only protocol messages; native output remains in durable session logs. The Go process invokes arguments directly and keeps settings/events separate from renderer capability.

## Portable package

From the repository root:

```powershell
rtk proxy powershell -NoProfile -File packaging/windows/order1886-go-build.ps1 -LegacyPackage "<verified portable package folder>" -Python "<build Python with PyInstaller>"
```

The builder produces a separate preview under `out/order1886-go-package/<UTC timestamp>/The Order 1886`. It is **Go only**: the previous Python GUI is no longer shipped, and an installation that still contains `The Order 1886 Legacy.exe` loses that file during the first update. Both normal and direct-play executable names are preserved, the dedicated native runtime and worker are included, the manifest advertises `order1886-update-2`, and relocated smoke checks run with a restricted PATH.

Windows needs WebView2. Startup was checked on the development machine with WebView2 installed; clean-machine missing-runtime and offline-install qualification remain open. Linux's existing preview is unchanged.

## Current boundaries

The source catalogue contains 47 fields and 19 mapped player settings. Keyboard/controller digital bindings use the matching runtime's SDL inventory, per-button defaults and digital unbinding. Physical axes/triggers, mouse and real touch input remain active; their independent remapping is unavailable. See [input evidence](../docs/verification/2026-10-19-input-remapping.md). The GPU readback selector keeps the existing relaxed default; selective/precise require a matching native receipt and remain experimental. Other requested modes remain visible with reasons and cannot be saved as working renderer options. Their presence is not a gold claim. Older Go previews retain their original catalogue/runtime.

The 13 existing language catalogs and game-language forwarding are reused. Newly written UI copy still needs translation/native-speaker review. Independent game text/voice selection remains open. Local trophy IDs and timestamps use the native store's checksum. Installed TRP artwork supplies locked/earned entries and progress; earned entries show their images and readable localized dates. Encrypted names/descriptions and a real unlock capture remain open. See [achievement evidence](../docs/verification/2026-10-19-achievements.md).

Updates check the selected channel, verify the GitHub asset, receipt, source, runtime and full file manifest, download into a private stage and replace only manifest-owned files. The replacement runs from a copy of the launcher before any window or worker exists, holds the installation and player-session locks, and writes a journal first; an interrupted update is recovered at startup and its previous payload is retained for rollback. Player saves, settings, unknown keys, mods and patches are never rewritten. `automatic_updates` is a startup check only and never installs without a click. HTILE metadata adaptation stays off unless the player opts in with a runtime that declares it.

See [verification](../docs/verification/2026-10-18-go-launcher.md) for exact evidence and remaining gold work.

