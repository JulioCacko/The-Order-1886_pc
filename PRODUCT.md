# The Order: 1886 launcher
<!-- impeccable:product-schema 1 -->

## Platform

Windows desktop (Linux preview), a Wails v2 window with the native title bar. Its UI is semantic HTML/CSS/TypeScript embedded in a Go executable; it is a desktop application, not a website.

## Stack

Go and Wails v2 for the launcher (`launcher-go/`), with embedded TypeScript/HTML/CSS. The Python worker (`launcher/order1886_worker.py`, packaged with PyInstaller) prepares the game and runs sessions; reuse it rather than duplicating backend logic.

## Users

Players with an extracted copy of The Order: 1886 in any edition (CUSA00076, CUSA00035, CUSA00070, CUSA00100, CUSA00670 or CUSA00785) who want to configure and attempt to start a session on Windows.

## Product Purpose

Make choosing the game folder, adjusting essential settings and starting a session straightforward. The cinematic launch bar keeps Play primary, with game folder and display / upscaling / frame-rate choices immediately available. The desktop launcher adopts the five-page structure of mateussmeneses/theorder1886-port: Home, Graphics, Performance, Game and Advanced. A persistent sidebar changes pages; the launch bar remains available on each page. The original composition remains available through `--classic`.

## Operating Context

The launcher is experimental emulator-backed compatibility software for The Order: 1886 (CUSA00076 tested; the other editions experimental). It starts a separate native runtime, keeps launcher state outside the original game folder and records session logs. It must work with a mouse and keyboard at ordinary Windows window sizes.

## Capabilities and Constraints

- Home actions: Play / Stop, Change game folder, Settings, Verify files and View logs. Closing the native window follows the launcher's session shutdown handling.
- Immediate choices: Windowed / Borderless / Fullscreen, FSR 1 / Linear presentation, and 30 FPS / experimental 60 FPS configuration.
- Graphics contains display, aspect ratio, output scaling and VSync. Performance contains frame rate and the overlay. Game contains folder selection, file verification, save backups/restoration and compatibility notes for patches and controls. Advanced contains the optional runtime executable, folders, logs, release and issue links.
- Page settings persist with Save settings, and starting from a settings page saves them before launch. Save restore requires an in-app confirmation and backs up the replaced saves. Save mutations and settings changes are disabled during a session.
- Preserve settings persistence, original-file protection, save handling, runtime identity checks, asynchronous session control and error logging.
- File and runtime readiness do not establish gameplay compatibility. Gameplay and 4K/60 FPS acceptance remain unverified; selected settings are not measured performance.
- UI verification must not launch the game, profile the GPU or attach debugger instrumentation.
- The launcher has no store, account system or fictional mod-management capabilities.

## Brand Commitments

Preserve The Order: 1886 identity, charcoal, muted brass, ivory, Georgia page headings and readable Segoe UI controls. Use the user's supplied official horizontal and stacked logos for Home and the sidebar; use the supplied official emblem for the launcher, runtime and executable icons. Do not recreate the game wordmark in a font. Use the user's supplied `2354440.jpg` as the bundled `launcher-art.jpg` background, with semantic UI over it. Preserve the source image bytes; adapt their display sizes at render time. The previous generated background and the player's `sce_sys/pic0.png` remain fallbacks. Never import another game's branding or engine claims.

## Evidence on Hand

The launcher is in `launcher-go/` (design record: `launcher-go/DESIGN.md`); the backend it drives is `launcher/order1886_worker.py` with `launcher/order1886_common.py`. Behavior checks are in `launcher-go/` Go tests, `launcher-go/frontend/tests/` and `tests/test_order1886_worker*.py`; packaging and CPU-only smoke checks are under `packaging/windows/`. Compatibility evidence is recorded in `docs/order1886-runtime-status.md`.


## Product Principles

- Prioritize starting a session over technical housekeeping.
- Keep essential configuration near Play and disclose advanced diagnostics progressively.
- Preserve player files and preferences.
- Distinguish configuration readiness from compatibility status.
- Use native, keyboard-accessible controls and readable text.
