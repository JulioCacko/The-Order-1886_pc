# Windows source build

Install MSYS2 in C:\msys64 (or set MSYS2_ROOT). In the CLANG64 shell:

```bash
pacman -S --needed git patch \
  mingw-w64-clang-x86_64-{toolchain,cmake,ninja,pkgconf,python} \
  mingw-w64-clang-x86_64-{vulkan-headers,vulkan-loader,vulkan-memory-allocator,glslang} \
  mingw-w64-clang-x86_64-{sdl3,fmt,boost,robin-map,xxhash,ffmpeg,zydis} \
  mingw-w64-clang-x86_64-{spirv-tools,spirv-headers,spirv-cross}
git submodule update --init --recursive
```

From the repository in PowerShell:

```powershell
& C:\msys64\usr\bin\bash.exe build.sh --test
```

The script initializes MSYS2 paths, handles Windows checkout line endings, configures CMake with CLANG64, and builds the dedicated order1886-runtime target. Outputs: out/order1886-runtime.exe, out/ps4-gpu-capabilities.exe and out/runtime-build.json. The receipt binds source revision, dirty state, compiler, source-file digest and submodule revisions to the executable SHA256.

Install Windows Python 3.11+ with Tk, Pillow and iced-x86 for source-launcher/image preparation. The package builder creates its private Python environment. Packaged users do not require Python or MSYS2.

The reference source supplied at D:\Emulator\PS4\shadPS4 was inspected at revision 5aa7ffa3f4f21bba827d7865ed8f69f98f993542 (0.20.1 WIP). It contained no Windows executable in the audited inventory. The reference directory is read-only implementation evidence and is not a runtime fallback.

The package builder creates `out/order1886-pyenv`. Once it exists, its installed
dependencies can run the complete Windows Python regression suite:

```powershell
& out/order1886-pyenv/Scripts/python.exe -m unittest discover -s tests
```

`build.sh --test` builds the runtime and semaphore fixtures in `out/gpu` on
Windows. The Python tests select those `.exe` files and provide their CLANG64
DLL path. A source Python without `iced-x86`, or absent native test binaries,
still reports the corresponding skips; those skips are not passing checks.

See docs/order1886-runtime-status.md for current real-game results. Source compilation and launcher tests do not establish rendering or gameplay.
