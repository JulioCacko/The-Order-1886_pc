# The Order: 1886 PC — development status

Updated **18 October 2026**. Verified implementation: `e4d02ff` plus documentation.
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
| Full Python suite | 321 passed, zero skips | Private package environment; 313.946 seconds |
| Windows native gate | 41 checks passed | Runtime, shader/IR, cache, input, media, queue and memory fixtures |
| SPIR-V | Three modules pass Vulkan 1.3 validation | Atomic structure and NaN math; no game image-quality claim |
| RTX 3070 cache smoke | Graphics and compute pass | Four hits, two compiles/saves, no rejects/cache errors |
| Portable package | All 15 relocated checks pass | Hashes, identity, helper closure, GUI/direct play and CPU preparation |
| Launcher images | Four fresh 1240 × 800 captures | Actual source UI, isolated state; no game launched |
| Gameplay/performance | Pending | No sustained 4K/60 or campaign acceptance |

The [verification receipt](verification/2026-10-18-donor-060.md) records commands,
artifacts and boundaries. Older reports retain their original dates and test scope.

## Runtime and package identity

| Field | Value |
| --- | --- |
| Verified source | `e4d02ff7dbbdcfdef960a9ea6a301c09fc86971f`, clean package snapshot |
| Runtime SHA256 | `700197eb1a3feb6700dcbf15037eeaff59de71d9e9dad77875416bbe8a64ed17` |
| Source-files SHA256 | `0b2672919c59d5089ab430938a2d8f2616dbada141019ec7b41bd9d5e003ee5c` |
| ABI / prepared format | `order1886-native-1` / `PS4BOOT5` |
| Renderer / cache ABI | `native-ps4` / `native-ps4-v1` |
| Shader binary / metadata / pipeline key | 16 / 10 / 8 |
| Local package | `20261018T170925Z-700197eb1a3f` |
| ZIP bytes | 108533689 |
| ZIP SHA256 | `6b3550c1f96e59b28bd9d84a35c524cd3c1c952c5609b14b5d0ca47cb6a00bff` |
| Local hardware | Ryzen 5 5600X, RTX 3070; not minimum requirements |

The local ZIP is under `dist/order1886/20261018T170925Z-700197eb1a3f/`, outside Git.
**The public download remains preview.3 from October 17.** Pushing source and
screenshots does not publish a replacement release ZIP. Shader version 16 rebuilds
old translations on the next game launch.

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
