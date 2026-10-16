# The Order: 1886 PC

Experimental Windows compatibility work for the original PS4 executable, with a dedicated Order launcher and runtime. The original intro sequence is visible; a functional menu and interactive 3D gameplay have **not** been verified.

Use your own extracted CUSA00076 game directory. Original game files remain unchanged; prepared images, settings, logs, caches and saves are stored separately. Game binaries and artwork are excluded from the portable package.

## Launch

Run `Launch The Order 1886.cmd` or `python launcher/order1886_launcher.py`, then select the game directory in Settings. Automatic runtime selection uses this installation's `bin/order1886-runtime.exe` or source build `out/order1886-runtime.exe`.

## Build and verification

Install the MSYS2 CLANG64 dependencies in [the Windows build instructions](docs/order1886-build.md), initialize submodules, then run from PowerShell:

```powershell
& C:\msys64\usr\bin\bash.exe build.sh --test
python -m unittest discover -s tests -p 'test_order1886*.py'
python order1886.py --runtime out/order1886-runtime.exe --check-imports --timeout 30
python order1886.py --runtime out/order1886-runtime.exe --timeout 45
```

The build produces `out/order1886-runtime.exe` and a SHA256-bound `out/runtime-build.json` receipt. The dedicated Order target removes inherited executable-injection hooks and restricts rendering to a PS4 compatibility baseline. Engine-specific behavior requires independent validation.

Runs record the command, executable/image hashes, source-build receipt, effective settings, exit status and fatal import under `user/order1886/logs`. An import audit does not execute the game. Vulkan initialization does not establish rendering or gameplay.

See [current runtime evidence and remaining gates](docs/order1886-runtime-status.md). Build, boot, menu, gameplay, 30-minute stability, performance and distribution are separate gates.

## Package

Run `packaging/windows/order1886-build.ps1` after a successful source build. Packages include the dedicated runtime, required DLLs, original launcher artwork, build identity and license notices. They require the player's existing game directory. Packaging does not establish game compatibility.

## Attribution

GPL-2.0-or-later. Reusable loader/build infrastructure derives from [FelipePrado0/gow3_pc](https://github.com/FelipePrado0/gow3_pc); PS4 graphics and API work derives from [shadPS4](https://github.com/shadps4-emu/shadPS4). Attribution and third-party licenses are retained. The Order uses a different engine; inherited title-specific patches and shader assumptions are not compatibility evidence.
