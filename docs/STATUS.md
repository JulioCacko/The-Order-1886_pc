# The Order: 1886 PC — development status

Updated **21 October 2026**; native resolution added **29 October 2026**. Preview 9 implementation: `b19c604`. Gameplay runs at about 53 FPS in the night courtyard on an RTX 3070, the launcher's graphics options reach the runtime, and the Linux package bundles its libraries ([verification](verification/2026-10-21-preview9-release.md)).
Cinematics render and a street route has been exercised, but performance remains
slow. Campaign progression, gameplay checkpoint save/load, long-session stability
and sustained 4K/60 remain unaccepted. Native 4K rendering (Graphics → Render resolution)
holds 30 FPS in gameplay on an RTX 3070, with drops to 27 FPS (67 ms frames) in the Chapter II
Council cutscene, and is experimental
([evidence](verification/2026-10-29-native-resolution.md)).

## Implemented and locally checked

- Opt-in [Go/Wails launcher prerelease](https://github.com/JulioCacko/The-Order-1886_pc/releases/tag/v0.1.0-go-preview.9): seven searchable pages, separate worker, validated autosave and local trophy history. [353 Python tests, Go/frontend checks, portable smoke and hosted Windows CI passed](verification/2026-10-18-go-launcher.md). Unavailable features are visible with reasons; this does not replace preview.4 or establish gold.
- Five-page Windows launcher with shared settings, keyboard navigation, scrolling,
  persistent Play/Stop, 13 UI language choices and English fallback.
- Configurable mouse-to-stick camera input, sensitivity and inverted Y. Focus loss,
  host UI and text entry release capture; Esc releases it and F6 toggles it.
- `Play The Order 1886.exe` shares settings, preflight, preparation, session locking,
  backups and logs with launcher Play. Desktop shortcuts are idempotent; first-run
  or invalid settings return to setup.
- Add to Steam supports closed-client shortcut updates with quoted paths, account
  discovery, preservation/backups, atomic replacement and idempotence.
- Backup/restore protects original files; numeric same-second ordering preserves
  the newest copy and restore safety backup.
- Game-page backup selection plus Play confirms restoration before launch; the
  game save APIs see restored slots/metadata in disposable fixtures. Older
  snapshots may lack Profile. In-game Continue/progression remains unverified.
- Launcher language also sets the next game's PS4 system language, including
  pt-BR. Matching installed assets are required; independent text/voice is open.
- Experimental Linux x86-64 bundle with Python/Tk and native dependency closure.
  Ubuntu 26.04/glibc 2.43+ required; Linux gameplay/GPU remains unqualified.
- Ordered `_data` asset overlays preserve originals and show conflicts. New mods
  remain disabled until selected. External executable patches remain unsupported.
- Shader-cache clearing is scoped to this installation and blocked during a session.
- Shader fixes cover unordered NaN comparisons, legacy math, trinary operations
  and exclusive float atomics; graphics pipeline key copies preserve hash bytes.
- Mapped-range epoch caching, busy-mutex lifetime protection and validated
  plaintext SELF/unpacked x86-64 ELF preparation.
- Source follow-up: protected upload copies use stable backing views and flexible-map splits retain physical offsets. [355 Python tests, 42 Windows native checks and focused Linux CI pass](verification/2026-10-18-readback-correctness.md); this native change is separate from the published preview ZIP and has no matched-gameplay acceptance yet.

See [donor reuse](order1886-donor-reuse.md), [input/direct play](order1886-input.md)
and [mod limits](order1886-mods.md). Passing fixtures do not establish gameplay quality.

## Current verification

Preview 9 (`b19c604`); the full record is [2026-10-21-preview9-release.md](verification/2026-10-21-preview9-release.md).

| Check | Result | Scope |
| --- | --- | --- |
| Full Python suite | 531 run, 19 skipped, no failures | Launcher, worker, packaging, timing, effects and tools |
| Windows native gate | 56 checks pass | Runtime, shader/IR, cache, input, media, queue, memory and IRQ fixtures |
| Portable packages | Windows and Linux smoke pass | Manifest hashes, entry points, worker protocol, update preflight; Linux bundled-library resolution |
| Updater | `updates.StageArchive` and the live check stage the published Windows zip | 218 files, clean source receipt |
| Linux on a clean system | Ubuntu 26.04.1 (WSL): every library resolves; the game reaches its title menu on lavapipe | No Linux GPU driver tested |
| Gameplay/performance | 53.2 FPS courtyard (p99 23 ms), 38 FPS hotel fight; RTX 3070, 60 FPS mode | No sustained 4K/60 or campaign acceptance |

Older reports keep their original dates and test scope.

## Runtime and package identity

| Field | Value |
| --- | --- |
| Verified source | `b19c6045b79adce1d1d87ed949c61dd03abda8c4`, clean package manifests |
| Windows runtime SHA256 | `881069e5e37a2c4adee22aaeb4c2d38ae42d7900c7a46508f40cfe92cef40a67` |
| Windows package | `order1886-go-windows.zip`, 107,332,965 bytes, SHA256 `61df772b5177fe52b065fd1cbc870b0d2a501cdb2dc7998c61a9edb79410ce67` |
| Linux package | `order1886-linux-x86_64.tar.gz`, 120,550,075 bytes, SHA256 `887dea5d34ce94435da423fbb1cfae53c4526594da7c201a918867e5e75b3776` |

## Current launcher

![Home page of the Go launcher (preview 9)](images/preview9/launcher-home.jpg)

![Game & Content page of the Go launcher (preview 9)](images/preview9/launcher-game.jpg)

These are captures of the real source launcher with isolated settings. They show
configuration, not measured FPS or gameplay. No game binaries, saves or fabricated
trophy unlocks are included.

## Runtime evidence and remaining blockers

The Chapter 2 copied-save run lasted 900.959 seconds, ended by forced configured
timeout, and preserved original save hashes. It exercised the targeted inactive
image guard 32 times without the 8,029-layer/assertion/fatal marker. Menus/loading
are included in that duration. Residual SRT errors and the original [#5 sequence](https://github.com/JulioCacko/The-Order-1886_pc/issues/5)
remain unresolved.

The user reported slow street performance. ETW samples identified mapped-range
lookup and guest task-queue activity. The optimization has production regressions
and synthetic measurements; the same-viewpoint street comparison is deferred.
No gameplay FPS improvement is claimed.

The donor readback/HTILE patch needs CPU-write cancellation, unmap/remap cleanup,
overlapping-watch handling, overflow-safe reads and guarded metadata values before
reuse. Saturation still assumes DX10_CLAMP; shader control propagation remains open.

Temporal providers, 4K/60, higher-FPS/QTE behavior, independent game text/voice,
official trophy metadata/live UI, automatic updates and wider vendor coverage are
not accepted. The update 1.02/fullscreen report [#23](https://github.com/JulioCacko/The-Order-1886_pc/issues/23)
has no matching reproduced crash proof. A prior full-PC freeze remains unexplained.

## Next acceptance work

1. Complete the deferred street comparison with matching settings and hashes.
2. Reproduce image-layer and update 1.02 reports while preserving validation.
3. Verify mouse aiming, menus/QTEs, checkpoint save/load and progression.
4. Qualify temporal inputs and each provider/hardware combination.
5. Record a 30-minute gameplay stability run and complete the [4K/60 plan](order1886-4k60-verification.md).

The [issue matrix](order1886-issue-status.md) separates completed host features
from partial implementation and gameplay-dependent acceptance.
