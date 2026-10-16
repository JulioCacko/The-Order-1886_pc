# The Order: 1886 PC — experimental PS4 compatibility runtime

Run the original **The Order: 1886** PlayStation 4 executable through a dedicated Windows launcher and Vulkan compatibility runtime. This project targets **CUSA00076** and reuses PS4 loader infrastructure and [shadPS4](https://github.com/shadps4-emu/shadPS4) graphics/API work.

**Development preview: gameplay is not yet verified.** Intro rendering, save initialization and existing-save reopening have been observed. Representative interactive 3D gameplay, checkpoint save/load, 30-minute stability and 4K/60 FPS acceptance remain open. This is community compatibility work, not an official PC release or a verified playable port.

[English](README.md) · [Português (Brasil)](README.pt-BR.md) · [Español](README.es.md)

![The Order: 1886 native Windows launcher showing cinematic artwork, game folder, display mode, FSR 1 upscaling, frame-rate selection and Play](docs/images/order1886-launcher.png)

*Actual launcher capture, 16 October 2026. The background is generated launcher illustration; this is not a gameplay screenshot. “30 FPS” is the selected limit, not a measured result.*

## Current compatibility status

| Area | Verified progress | Remaining gate |
| --- | --- | --- |
| Windows launcher | Play/Stop, folder selection, essential graphics controls, advanced settings, logs and keyboard navigation | Broader Windows/DPI coverage |
| Native runtime | Local build, eight native CPU checks and SHA256-bound build identity | Compatibility beyond observed startup |
| Boot and rendering | Original executable reaches intro and an animated background | Legible in-game menu and representative interactive 3D gameplay |
| Save handling | Save initialization, a 102400-byte SYSTEM.DAT, and reopening the existing save | Checkpoint progression, save/load and restart during gameplay |
| Performance | FSR 1 presentation and opt-in experimental 60 FPS profile | Repeatable 4K output measurements and sustained 60 FPS |
| Stability | Two bounded 120-second recovery runs ended at the configured timeout | Cause of a prior full-PC freeze and a 30-minute gameplay run |

Read the **[full current status report](docs/STATUS.md)** for build identity, verification, blockers and implementation history. The [runtime evidence record](docs/order1886-runtime-status.md) retains older diagnostic results separately.

## Start the Windows launcher

Use your own extracted CUSA00076 directory containing `eboot.bin`, `sce_sys` and `sce_module`. **No game executable, game dump or player save is distributed.** Original files remain unchanged; prepared images, settings, caches, logs, saves and backups are stored separately.

For a locally built portable package:

1. Extract the complete ZIP to a writable folder. Keep `bin`, `_internal` and the executable together.
2. Open **The Order 1886.exe**.
3. Choose **Game folder** directly in the launch bar.
4. Start with **30 FPS**. Choose a display mode and **FSR 1** or Linear output scaling.
5. Press **Play**. Use **View logs** to inspect progress or **Stop session** to end a session.

For a source checkout, run `Launch The Order 1886.cmd` or:

```powershell
python launcher/order1886_launcher.py
```

Automatic runtime selection uses this installation's `bin/order1886-runtime.exe` or source build `out/order1886-runtime.exe`. Settings provides an optional runtime override. Packaged users do not need Python or MSYS2. There is no verified Linux package for this Order-specific target.

## Graphics settings and the 4K/60 FPS target

The launcher provides Windowed, Borderless and Fullscreen modes, FSR 1 spatial or Linear presentation, VSync, and a performance overlay (F9). **60 FPS is opt-in and experimental**: timing-sensitive content, including Chapters 6 and 9, still requires verification. A frame-rate limit or host presentation rate does not prove the game produces that many new frames.

The agreed target is **3840 × 2160 output with upscaling acceptable**, preserved scene detail and sustained 60 FPS during gameplay. That target has not passed. Cold startup observations around 13–18 reported FPS are diagnostic observations, not a playable-performance benchmark. See the [4K/60 acceptance plan](docs/order1886-4k60-verification.md).

## Build and test

Follow the [Windows source-build instructions](docs/order1886-build.md), initialize the required submodules, then run from PowerShell:

```powershell
& C:\msys64\usr\bin\bash.exe build.sh --test
python -m unittest discover -s tests -p 'test_*.py'
python launcher/order1886_launcher.py --smoke-test
```

The build emits `out/order1886-runtime.exe` and `out/runtime-build.json`, binding the runtime SHA256 to source/build metadata. The GUI smoke check tests the launcher without starting the game. CPU tests, Vulkan initialization and shader validation are separate from gameplay acceptance.

Build a portable preview after the native build succeeds:

```powershell
./packaging/windows/order1886-build.ps1
```

The builder includes the dedicated runtime, required DLLs, generated launcher illustration, build identity and license notices. Use the [portable smoke verifier](packaging/windows/order1886-smoke.py) to check a relocated package. Local checks do not prove successful GitHub Actions or a published release; [Actions](https://github.com/JulioCacko/The-Order-1886_pc/actions) and [Releases](https://github.com/JulioCacko/The-Order-1886_pc/releases) show actual availability.

## Troubleshooting and contributing

Use **View logs → Open log folder**. When [reporting an issue](https://github.com/JulioCacko/The-Order-1886_pc/issues), include the matching `user/order1886/logs/last-run.json`, boot/session log, runtime SHA256, game metadata, GPU/driver and reproduction steps. Remove private paths if needed; do not upload game binaries or saves.

A prior instrumented session coincided with a full-PC freeze requiring a reset; its cause remains unknown. Debugger, RenderDoc and ETW availability do not establish successful profiling. Preserve that evidence before changing runtime behavior. Contributions should address a reproducible blocker and include focused verification.

## License and attribution

[GPL-2.0-or-later](LICENSE). Reusable loader/build infrastructure derives from [FelipePrado0/gow3_pc](https://github.com/FelipePrado0/gow3_pc); PS4 graphics and API work derives from [shadPS4](https://github.com/shadps4-emu/shadPS4). Required provenance and third-party licenses are retained. The Order uses a different game engine; another title's patches or performance are not compatibility evidence.

The Order: 1886 is associated with Ready at Dawn and Sony Computer Entertainment. This community project is not affiliated with or endorsed by them.
