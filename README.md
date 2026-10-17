<p align="center"><img src="launcher/order1886/logo-horizontal.png" width="720" alt="The Order: 1886 official logo"></p>
<h1 align="center">The Order: 1886 — PC</h1>

<p align="center">Native x86-64 execution · PS4 compatibility runtime · Vulkan graphics</p>

<p align="center">
  <a href="README.pt-BR.md"><b>Português (Brasil)</b></a> ·
  <a href="README.es.md">Español</a> ·
  <a href="https://github.com/JulioCacko/The-Order-1886_pc/releases/download/v0.1.0-preview.3/order1886-windows.zip"><b>Download Windows ZIP</b></a> ·
  <a href="https://github.com/JulioCacko/The-Order-1886_pc/releases">Releases</a> ·
  <a href="https://github.com/JulioCacko/The-Order-1886_pc/issues">Report a problem</a>
</p>

<p align="center">
  <a href="https://github.com/JulioCacko/The-Order-1886_pc/actions/workflows/windows-zip.yml"><img src="https://github.com/JulioCacko/The-Order-1886_pc/actions/workflows/windows-zip.yml/badge.svg" alt="Windows build"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-GPL--2.0--or--later-blue" alt="GPL-2.0-or-later"></a>
</p>

> **In development.** The game boots and renders 3D cinematics. Interactive gameplay, checkpoint save/load and sustained performance still need validation. The supplied October 17 session ends in a Vulkan image-limit assertion. See [Status](#status).

**The Order: 1886** for PlayStation 4, running on a PC through a dedicated
compatibility runtime. The original x86-64 executable runs on the host CPU,
PS4 system interfaces are reimplemented, and a
[shadPS4-derived video core](https://github.com/shadps4-emu/shadPS4) translates
GPU commands and shaders to Vulkan. The current target is **CUSA00076 on Windows**.

> **No game files are included.** You need your own extracted copy. This is an
> unofficial community project, not an official PC release.

## Video demonstration

[![Watch The Order: 1886 running on PC](https://i.ytimg.com/vi/wpNkwih0cxI/hqdefault.jpg)](https://youtu.be/wpNkwih0cxI)

[**Watch the demonstration on YouTube**](https://youtu.be/wpNkwih0cxI) — video evidence of the project running on PC, published by **Julio Cacko**. Click the thumbnail to watch.

![A rendered cinematic from the supplied October 17 recording](docs/images/order1886-cinematic-20261017.jpg)

<sub>Actual capture at 15:00 in the supplied October 17 recording, reduced from 1920×1080. This is a cinematic, not proof of interactive gameplay or a performance benchmark.</sub>

## What's new

- **Five-page launcher:** Home, Graphics, Performance, Game and Advanced, with sidebar navigation and Play/Stop always available. Adapted from [mateussmeneses/theorder1886-port](https://github.com/mateussmeneses/theorder1886-port), using this project's runtime and settings.
- **Save management:** browse backups, create a backup and restore one from the Game page. Restoring first backs up the current saves. Save operations are disabled while a session is running.
- **Graphics and timing:** window modes, FSR 1 or Linear presentation, aspect-ratio selection, VSync, F9 overlay and an opt-in experimental 60 FPS recipe.
- **Runtime hardening:** speculative SRT faults no longer rewrite shared walkers, identical walkers reuse generated code, and mapped-range snapshots refresh after map/unmap. These changes have not yet been measured in gameplay.
- **Descriptor diagnostics:** ORDER1886_DIAG_RESOURCE_SHARPS=1 now reaches the runtime through the source launcher for raw image descriptor logging.
- **Clearer evidence:** the supplied recording shows later 3D cinematics; the boot log identifies a concrete image-array-layer failure. The [reuse assessment](docs/order1886-reference-reuse.md) records what was adapted and which runtime changes need investigation.

## Status

| Area | Current evidence | Still to verify |
| --- | --- | --- |
| Boot and video | Logos and later 3D cinematics in the supplied recording | Interactive gameplay and progression |
| Windows launcher | Five pages, settings, Play/Stop, logs and backup/restore tools | Broader Windows and DPI coverage |
| Saves | Initialization, SYSTEM.DAT creation and reopening an existing save | Checkpoint saves, load and restart during gameplay |
| Graphics stability | October 17 log captures the failing image descriptor | Root cause of 8,029 requested layers versus a device limit of 2,048 |
| Performance | FSR 1 presentation and experimental timing recipe implemented | Repeatable 4K output and sustained 60 FPS during gameplay |
| Long sessions | A roughly 15-minute recording was supplied; sampled frames show cinematics | A 30-minute gameplay stability run |
| Platforms | Dedicated Windows source build and portable packaging | An Order-specific Linux package |

See the [full status report](docs/STATUS.md),
[runtime history](docs/order1886-runtime-status.md) and
[4K/60 acceptance plan](docs/order1886-4k60-verification.md).
Older reports retain their original verification scope; the recording is
additional evidence, not a claim that all previous gates have passed.

## Download and start

**[Download the Windows launcher ZIP](https://github.com/JulioCacko/The-Order-1886_pc/releases/download/v0.1.0-preview.3/order1886-windows.zip)** ·
[Release notes](https://github.com/JulioCacko/The-Order-1886_pc/releases/tag/v0.1.0-preview.3) ·
[English/Portuguese setup guide](https://github.com/JulioCacko/The-Order-1886_pc/releases/download/v0.1.0-preview.3/QUICKSTART.txt)

The preview includes the launcher, dedicated runtime, required libraries and
**`QUICKSTART.txt`**. No Python, MSYS2 or compiler is required. Download
`order1886-windows.zip`; GitHub's “Source code” archives are for developers.
The release also provides a ZIP checksum. Game files are supplied separately
by you; this preview retains the [known compatibility limitations](#status).

For a portable Windows package:

1. Extract the entire ZIP to a writable folder. Keep the executable, `bin` and `_internal` together.
2. Read **QUICKSTART.txt**, then open **The Order 1886.exe**.
3. Choose your extracted **CUSA00076** folder. It must contain `eboot.bin`, `sce_sys`, `sce_module`, `_data` and `archivemap.bin`.
4. Start with **30 FPS**, choose a display mode and press **Play**.
5. Use **Advanced → View session log** for progress, or **Stop session** to end the session.

Packaged users do not need Python or MSYS2. Original game files stay unchanged;
prepared images, settings, caches, logs, saves and backups live under the
installation's `user/order1886` folder.

For a source checkout, open `Launch The Order 1886.cmd` or run:

```powershell
python launcher/order1886_launcher.py
```

## The launcher

![The five-page Windows launcher with a persistent launch bar](docs/images/order1886-desktop.png)

<sub>Actual launcher capture using the wallpaper supplied by the user on October 17. It is not a gameplay screenshot. The selected 30 FPS option is a limit, not a measurement.</sub>

| Page | What you can do |
| --- | --- |
| **Home** | Choose the game folder, display, scaling and frame rate; start or stop a session |
| **Graphics** | Set window mode, original or experimental 16:9 aspect, FSR 1/Linear scaling and VSync |
| **Performance** | Choose 30 FPS or experimental 60 FPS; configure the F9 performance overlay |
| **Game** | Select and verify files, open the data folder, create or restore save backups |
| **Advanced** | Select an optional runtime, inspect logs, open folders, releases and support |

Use **Save settings** after editing a page. Starting from a settings page saves
its values before launch. The launch bar stays available on every page. Press
**Escape** to return Home; native controls support keyboard navigation.

The original cinematic launcher remains available:

```powershell
python launcher/order1886_launcher.py --classic
```

The reference's unvalidated GPU switches, updater, external patches/mods and
controller remapping are not enabled here. See the
[feature mapping and source revisions](docs/order1886-reference-reuse.md).

## Graphics and performance

**FSR 1** is spatial presentation scaling; temporal FSR and DLSS are not exposed
by this build. The 4K/60 target is **3840×2160 output with upscaling acceptable**,
preserved detail and sustained 60 FPS in gameplay. It has not passed.

**60 FPS is experimental.** The timing recipe warns of possible QTE softlocks
in Chapters 6 and 9. A host presentation rate or selected cap does not establish
that the game produces that many new frames. Use the 30 FPS baseline first.

## Known problems and reporting

| Problem | What to do |
| --- | --- |
| `Image exceeds device format limits`, `layers=8029/2048` | Preserve the boot log and matching `last-run.json`. This descriptor exceeds the device limit; a cause or fix has not been established. |
| Low or varying frame rate | Include the scene, settings, GPU/driver and matching log. Shader compilation and compatibility work remain in progress. |
| Runtime missing or identity rejected | Keep the complete package together, or build a matching runtime. Use Advanced for an explicit runtime override. |
| Experimental 60 FPS timing problems | Return to 30 FPS and report the chapter and reproduction steps. |

Open **Advanced → Open log folder**. When
[reporting a problem](https://github.com/JulioCacko/The-Order-1886_pc/issues), include
`last-run.json`, the matching boot/session log, runtime SHA256, game metadata,
GPU/driver and reproduction steps. Review logs for personal paths before sharing;
do not upload game binaries or saves.

A previous instrumented session coincided with a full-PC freeze requiring a
reset; its cause remains unknown. The October 17 image assertion is separate
evidence and does not establish the cause of that freeze.

## Building from source

Follow the [Windows build guide](docs/order1886-build.md) and initialize its
required submodules. From PowerShell:

```powershell
& C:\msys64\usr\bin\bash.exe build.sh --test
python -m unittest discover -s tests -p 'test_*.py'
python launcher/order1886_launcher.py --smoke-test
```

After the native build succeeds, create a portable preview:

```powershell
./packaging/windows/order1886-build.ps1
```

The builder bundles the launcher, dedicated runtime, required DLLs, build
identity and license notices. The
[portable smoke verifier](packaging/windows/order1886-smoke.py) checks a relocated
package without starting gameplay. Build, CPU and launcher checks are separate
from graphics and gameplay acceptance.

## How it works

| Layer | Role |
| --- | --- |
| Loader | Prepares a hash-checked copy of the original executable and links its modules |
| Runtime | Reimplements the PS4 system interfaces used by this title |
| Video | Translates PS4 GPU commands and shaders to Vulkan/SPIR-V |
| Launcher | Configures the dedicated backend and manages sessions, logs and save backups |

## Credits and license

[GPL-2.0-or-later](LICENSE). Loader/build infrastructure derives from
[FelipePrado0/gow3_pc](https://github.com/FelipePrado0/gow3_pc); graphics/API work
derives from [shadPS4](https://github.com/shadps4-emu/shadPS4).
The five-page launcher structure is adapted from
[mateussmeneses/theorder1886-port](https://github.com/mateussmeneses/theorder1886-port).
README organization is inspired by [HayatoG/iss_pc](https://github.com/HayatoG/iss_pc).
Exact revisions and reuse decisions are recorded in the
[assessment](docs/order1886-reference-reuse.md); portable builds retain the
[attribution notice](packaging/windows/ATTRIBUTION-Order1886.txt).

The Order: 1886 belongs to its respective rights holders, including Sony
Computer Entertainment and Ready at Dawn. This project is not affiliated with
or endorsed by them. No game executable, dump or player save is distributed.
