# Issue implementation and acceptance — 18 October 2026

Reviewed against the acceptance lists in
[JulioCacko/The-Order-1886_pc](https://github.com/JulioCacko/The-Order-1886_pc/issues).
Evidence: [verified implementation](verification/2026-10-18-donor-060.md),
[runtime record](verification/2026-10-18-gold-work.md), release source at `54242e0`.
Preview.4 adds Windows/Linux packages, selected-save restoration before Play and game system-language forwarding. See the [release receipt](verification/2026-10-18-preview4-release.md).

## Completed host features

| Issue | Result | Verification |
| --- | --- | --- |
| [#19](https://github.com/JulioCacko/The-Order-1886_pc/issues/19) Direct play | Implemented | Exact `Play The Order 1886.exe` is packaged; shared settings/session worker, preflight, logs, setup recovery and idempotent desktop shortcuts. Relocated checks cover spaces/Unicode and saved configuration. |

This resolves the direct-play host integration. Game rendering, progression and
performance are tracked separately.

## Remaining work

| Issues | Status | Concrete gap |
| --- | --- | --- |
| [#1](https://github.com/JulioCacko/The-Order-1886_pc/issues/1) Fullscreen/aspect | Partial | Modes and guarded 16:9 exist; framing/HUD/gameplay acceptance pending. |
| [#2](https://github.com/JulioCacko/The-Order-1886_pc/issues/2) Resolution/presets | Partial | Linear/FSR 1 exist; pixel-matched original, measured internal/output sizes, native 4K and temporal presets not accepted. |
| [#3](https://github.com/JulioCacko/The-Order-1886_pc/issues/3) 4K/60 | Validation pending | Street remains slow; no sustained 4K/60 or timing acceptance. |
| [#4](https://github.com/JulioCacko/The-Order-1886_pc/issues/4) Input | Partial | Mouse-to-stick preferences/focus and guidance exist; remapping, direct 1:1 camera and gameplay/QTE proof remain. |
| [#5](https://github.com/JulioCacko/The-Order-1886_pc/issues/5) Image-layer crash | Validation pending | Guards and copied-save run demonstrate mitigation; original sequence and residual SRT errors remain. |
| [#6](https://github.com/JulioCacko/The-Order-1886_pc/issues/6) Roadmap | In progress | Child features and acceptance remain open. |
| [#7](https://github.com/JulioCacko/The-Order-1886_pc/issues/7) Temporal inputs | In progress | Bridges require validated depth, motion, jitter, UI composition and history. |
| [#8](https://github.com/JulioCacko/The-Order-1886_pc/issues/8) UI/languages | Partial | Five pages and 13 choices exist; remaining feature surfaces, Arabic RTL/CJK and broad DPI acceptance are open. |
| [#9](https://github.com/JulioCacko/The-Order-1886_pc/issues/9) Updates | Open | Manual release links; no transactional automatic updater. |
| [#10](https://github.com/JulioCacko/The-Order-1886_pc/issues/10), [#11](https://github.com/JulioCacko/The-Order-1886_pc/issues/11), [#12](https://github.com/JulioCacko/The-Order-1886_pc/issues/12), [#13](https://github.com/JulioCacko/The-Order-1886_pc/issues/13) Providers | Open | SDK/bridge presence is not gameplay-qualified DLSS, FSR 3.1/4 or XeSS; license, packaging and hardware gates remain. |
| [#14](https://github.com/JulioCacko/The-Order-1886_pc/issues/14) Timing/caps | Partial | Native 30/experimental 60 exist; 90/unlocked and Chapter 6/9 behavior not accepted. |
| [#15](https://github.com/JulioCacko/The-Order-1886_pc/issues/15), [#16](https://github.com/JulioCacko/The-Order-1886_pc/issues/16) Cheats/effects | Open | No complete verified option matrix or matched gameplay proof. |
| [#17](https://github.com/JulioCacko/The-Order-1886_pc/issues/17) Mods/patches | Partial | Ordered asset overlays pass fixtures; external executable patches, real mods and update preservation remain. |
| [#18](https://github.com/JulioCacko/The-Order-1886_pc/issues/18) Steam shortcut | Implementation checked; acceptance pending | 24 integration fixtures cover discovery, quoting/Unicode, preservation, atomic writes, running-client refusal and idempotence. A live Steam shortcut launch with saved settings remains unverified; no personal library was changed during review. |
| [#20](https://github.com/JulioCacko/The-Order-1886_pc/issues/20) In-game UI/text/cache | Partial | Overlay/input plumbing and safe clearing exist; text-dialog applicability and complete in-game focus/settings acceptance remain. |
| [#21](https://github.com/JulioCacko/The-Order-1886_pc/issues/21) Text/voice | Partial | Launcher selection now forwards the verified PS4 system-language ID (including pt-BR) on next launch. Matching game assets, visible gameplay acceptance and independent text/voice controls remain required. |
| [#22](https://github.com/JulioCacko/The-Order-1886_pc/issues/22) Achievements | Partial | ABI unlock IDs/timestamps persist in fixtures; official metadata, names/icons, live UI and real unlock capture remain. |
| [#23](https://github.com/JulioCacko/The-Order-1886_pc/issues/23) Update 1.02 | Validation pending | The shown 40 FPS rejection does not resolve the separate reported 60 FPS/fullscreen crash. |

## Screenshot provenance

Four source-launcher captures were made on October 18 using the actual
`DesktopLauncher` and Windows Pillow window capture, after the Computer Use helper
failed with `foreground window did not report a process id`. The capture fixture
used isolated settings, did not invoke Play, and closed its own window after
capturing Home, Graphics, Game utilities and Advanced at 1240 × 800. No UI or game
output was generated or composited. The selected 30 FPS is a setting.

Images: `docs/images/order1886-{home,graphics,game,advanced}-20261018.png`.
The October 17 cinematic image remains dated as historical evidence.
