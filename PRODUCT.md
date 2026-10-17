# The Order: 1886 launcher
<!-- impeccable:product-schema 1 -->

## Platform

Windows desktop, using native Tkinter widgets. The native Windows title bar and widget semantics are intentional. A web or mobile platform label would misdescribe this application.

## Stack

Python 3, Tkinter and Pillow, packaged with PyInstaller. Reuse the existing launcher and runtime backend.

## Users

Players with an extracted CUSA00076 copy of The Order: 1886 who want to configure and attempt to start a session on Windows.

## Product Purpose

Make choosing the game folder, adjusting essential settings and starting a session straightforward. The cinematic launch bar keeps Play primary, with game folder and display / upscaling / frame-rate choices immediately available. The desktop launcher adopts the five-page structure of mateussmeneses/theorder1886-port: Home, Graphics, Performance, Game and Advanced. A persistent sidebar changes pages; the launch bar remains available on each page. The original composition remains available through `--classic`.

## Operating Context

The launcher is experimental emulator-backed compatibility software for CUSA00076. It starts a separate native runtime, keeps launcher state outside the original game folder and records session logs. It must work with a mouse and keyboard at ordinary Windows window sizes.

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

Implementation is in `launcher/order1886_launcher.py`; behavior checks are in `tests/test_order1886_launcher.py`; packaging and CPU-only smoke checks are under `packaging/windows/`. Compatibility evidence is recorded in `docs/order1886-runtime-status.md`.

The approved composition is `.impeccable/mocks/concept-a.png`. Native captures live under `.impeccable/review/`; their review status is separate from code or packaging checks. The composition, specification and asset-plate stages are closed, while the hero webgate remains open with native measurement limitations. This file does not declare an Impeccable finish verdict or gameplay certification.

## Product Principles

- Prioritize starting a session over technical housekeeping.
- Keep essential configuration near Play and disclose advanced diagnostics progressively.
- Preserve player files and preferences.
- Distinguish configuration readiness from compatibility status.
- Use native, keyboard-accessible controls and readable text.
