# Preview.4 release verification — 18 October 2026

Package version **0.1.3**, tag **v0.1.0-preview.4**. Runtime and launcher source:
`54242e0e5ab05644bff2df56813d39f654659b30`; both embedded receipts report
`source_dirty=false`. The tag also includes release documentation added afterward.
Preview.3 remains available for rollback.

## Changes

- Game-page backup selection plus Play asks for restoration confirmation before
  launch. Cancel/error blocks launch; a safety backup preserves current saves.
  Explicit restore explains Continue/Load and external session locking blocks
  concurrent save writes. Production savedata search/mount fixtures see restored
  Playthrough00 and Profile data and metadata. CUSA00076 declares
  `INSTALL_DIR_SAVEDATA=CUSA00035`; older snapshots may lack Profile.
- The 13 launcher language choices now forward verified PS4 system-language IDs
  through the backend to `sceSystemServiceParamGetInt`. Brazilian Portuguese is
  ID 17. Malformed/out-of-range native values fall back to English. The game
  requires matching installed assets; independent text/voice remains open.
- Linux packaging bundles Python/Tk, the native runtime/renderer and dependency
  closure with licenses. Fresh-HOME startup creates missing parent directories;
  unavailable optional Vulkan header extensions are guarded.
- Four actual launcher screenshots were refreshed with isolated settings.

## Checks

| Check | Result | Boundary |
| --- | --- | --- |
| Windows Python | 340 run, all pass, zero skips; 222.190 s | Includes 8 save-selection cases and production save restore round-trip |
| Linux Python | 340 run, 21 skipped, no failures; 105.735 s | Windows-specific checks skipped; Tk checked under Xvfb |
| Windows native `build.sh --test` | 41 checks pass | Includes RTX 3070 cache fixtures; no new gameplay acceptance |
| Linux native `build.sh --test` | Pass | Linux branch's shader/cache/input/runtime/media/services/ISA subset and trophy tests; not the Windows 41-target gate |
| Relocated Windows package | All 15 checks pass | Minimal PATH, hashes, identity, GUI/direct play and 30/60 CPU preparation |
| Relocated Linux package | All 10 checks pass | Minimal environment, all 750 manifest files, identity/dependency closure, GUI/direct play and 30/60 CPU preparation |
| Archives | ZIP CRC pass; tar safe paths/normalized UID/GID | Windows 1,538 members; Linux 782; excluded player/game files checked |
| Workflow | `act --list` parses Linux workflow | Full local workflow execution unavailable: container engine offline |

Commands: `build.sh --test`, `python -m unittest discover -s tests`,
`packaging/windows/order1886-build.ps1 -SkipDependencyInstall`,
`python packaging/linux/order1886-package.py`, and each platform's
`order1886-smoke.py` with the local CUSA00076 dump. Linux GUI checks used Xvfb.
Local raw evidence: `out/order1886-evidence/release-20261018/` (not distributed).
Release asset `release-verification.json` records package hashes and scope.

## Artifact identity

| Package | Bytes | SHA256 |
| --- | ---: | --- |
| `order1886-windows.zip` | 108539768 | `ec613979ab159b7042554597deff9d9cb91b7670125152fa837a8adc2ebb74d6` |
| `order1886-linux-x86_64.tar.gz` | 129083903 | `a7fcfd9a57c02821b8690f6aa3320c134764c48b70027a46b777a57bdc2f96ed` |

Windows runtime SHA256:
`ca77edaf93ccec956b20263cb3b9a0c36b1b4496e5437e080d5f6d95b850f1e9`.
Linux runtime SHA256:
`cea8cac77b276bcec8b61365c420124ccd9340fdd44d1dde514240c54c24ac64`.

Linux was built/host-tested on Ubuntu/WSL **26.04.1, glibc 2.43, x86-64**.
Requires Ubuntu 26.04/glibc 2.43+, X11/XWayland and a Vulkan driver. Older
distributions/SteamOS and Linux GPU/gameplay are unqualified. The unused optional
FSR-Vulkan submodule is absent from that snapshot; its bridge is not shipped.

No player saves were restored or modified and no game session was started for
these fixes. Continue/chapter progression and visible game localization remain
unverified. Missing language assets cannot be supplied by an OS-language choice.
Independent text/voice, long-session stability, Chapters 6/9 timing and sustained
4K/60 remain open. Prior graphics evidence keeps its original scope/date.
