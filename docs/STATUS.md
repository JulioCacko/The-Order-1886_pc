# The Order: 1886 PC — development status

Updated **18 October 2026**. Preview.4 implementation: `54242e0` plus release documentation.
Cinematics render and a street route has been exercised, but performance remains
slow. Campaign progression, gameplay checkpoint save/load, long-session stability,
native 4K and sustained 4K/60 remain unaccepted.

## Implemented and locally checked

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

See [donor reuse](order1886-donor-reuse.md), [input/direct play](order1886-input.md)
and [mod limits](order1886-mods.md). Passing fixtures do not establish gameplay quality.

## Current verification

| Check | Result | Scope |
| --- | --- | --- |
| Full Python suite | Windows 340 pass, zero skips; Linux 340 run, 21 skips | Integrated save/language and packaging changes |
| Windows native gate | 41 checks passed | Runtime, shader/IR, cache, input, media, queue and memory fixtures |
| Linux native gate | `build.sh --test` passed | Linux shader/cache/input/runtime/media/services/ISA subset |
| SPIR-V | Three modules pass Vulkan 1.3 validation | Atomic structure and NaN math; no game image-quality claim |
| RTX 3070 cache smoke | Graphics and compute pass | Four hits, two compiles/saves, no rejects/cache errors |
| Portable packages | Windows 15 / Linux 10 relocated checks pass | Hashes, identity, dependency closure, GUI/direct play and CPU preparation |
| Launcher images | Four fresh 1240 × 800 captures | Actual source UI, isolated state; no game launched |
| Gameplay/performance | Pending | No sustained 4K/60 or campaign acceptance |

The [release receipt](verification/2026-10-18-preview4-release.md) records commands,
artifacts and boundaries. Older reports retain their original dates and test scope.

## Runtime and package identity

| Field | Value |
| --- | --- |
| Verified source | `54242e0e5ab05644bff2df56813d39f654659b30`, clean package snapshots |
| Windows runtime SHA256 | `ca77edaf93ccec956b20263cb3b9a0c36b1b4496e5437e080d5f6d95b850f1e9` |
| Linux runtime SHA256 | `cea8cac77b276bcec8b61365c420124ccd9340fdd44d1dde514240c54c24ac64` |
| ABI / prepared format | `order1886-native-1` / `PS4BOOT5` |
| Renderer / cache ABI | `native-ps4` / `native-ps4-v1` |
| Shader binary / metadata / pipeline key | 16 / 10 / 8 |
| Windows package | `20261018T225850Z-ca77edaf93cc` |
| ZIP bytes | 108539768 |
| ZIP SHA256 | `ec613979ab159b7042554597deff9d9cb91b7670125152fa837a8adc2ebb74d6` |
| Local hardware | Ryzen 5 5600X, RTX 3070; not minimum requirements |

**[Preview.4 downloads](https://github.com/JulioCacko/The-Order-1886_pc/releases/tag/v0.1.0-preview.4)**
include Windows and experimental Linux packages, checksums and setup guides.
Preview.3 remains available for rollback. Shader version 16 rebuilds old
translations on the next game launch.

## Current launcher

![Home, captured October 18](images/order1886-home-20261018.png)

![Game utilities with desktop and Steam actions](images/order1886-game-20261018.png)

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

Temporal providers, native 4K, higher-FPS/QTE behavior, independent game text/voice,
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
