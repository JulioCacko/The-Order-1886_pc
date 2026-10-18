# The Order: 1886 Go launcher preview

Wails v2.17.0, Go and locally embedded TypeScript/HTML/CSS. This is an opt-in migration preview; the existing Python launcher remains the default distribution path.

## Develop

Requires Go 1.24+, Node.js compatible with Vite 7, and Python with the existing project's preparation dependencies.

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

The builder produces a separate preview under `out/order1886-go-package/<UTC timestamp>/The Order 1886`. It keeps the previous GUI as `The Order 1886 Legacy.exe`, preserves both normal/direct-play executable names, includes the dedicated native runtime and worker, writes a SHA256 manifest and runs relocated smoke checks with restricted PATH.

Windows needs WebView2. Startup was checked on the development machine with WebView2 installed; clean-machine missing-runtime and offline-install qualification remain open. Linux's existing preview is unchanged.

## Current boundaries

The catalogue contains 43 fields; 15 existing player settings are writable. Other requested modes remain visible with reasons and cannot be saved as working renderer options. Their presence is not an implementation or gold claim.

The 13 existing language catalogs and game-language forwarding are reused. Newly written UI copy still needs translation/native-speaker review. Independent game text/voice selection remains open. Local trophy IDs and timestamps use the native store's checksum; official names/icons and a real unlock capture remain open.

See [verification](../docs/verification/2026-10-18-go-launcher.md) for exact evidence and remaining gold work.

