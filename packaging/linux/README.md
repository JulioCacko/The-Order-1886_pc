# Linux x86-64 experimental preview

This build targets **Ubuntu 26.04 / glibc 2.43 or newer, x86-64**. It was built and
host-tested in Ubuntu/WSL. Older distributions and SteamOS are not qualified.
An X11/XWayland desktop and a Vulkan 1.3-capable GPU/driver are required for game
rendering. Graphics drivers and glibc are supplied by your distribution.

1. Verify `order1886-linux-x86_64.tar.gz.sha256` with `sha256sum -c`.
2. Extract the whole archive into a writable directory. Keep the launchers,
   `order1886-launcher`, `_internal` and `bin` together.
3. Run `./The\ Order\ 1886`, select your extracted CUSA00076 game folder and save
   your settings. Game content is not included.
4. Start with original aspect ratio and 30 FPS. Use `./Play\ The\ Order\ 1886`
   for direct launch with the same saved configuration.

The package includes its Python/Tk runtime and native dependency closure, except
host glibc and graphics drivers. Prepared images, logs, saves and settings remain
in `user/order1886`; preserve this folder when upgrading. Stop the game before
updating and extract a new version separately before copying your user data.

Windows desktop-shortcut and Windows Steam-discovery actions are not Linux
integrations. Use your desktop/Steam client to add the direct-play script manually.
Independent game text/voice, live achievements and automatic updating remain open.

Host/bootstrap and CPU checks do not establish Linux gameplay, GPU compatibility,
checkpoint progression, long-session stability or sustained 4K/60. The 60 FPS and
16:9 modes remain experimental; Chapters 6 and 9 have known timing risks.

## Build

Initialize the native submodules from the Windows build guide. On Ubuntu 26.04,
install CMake, Ninja, Clang, pkg-config, SDL3/Vulkan development files, Vulkan Memory
Allocator, fmt, Boost, robin-map, xxhash, FFmpeg development files, Zydis, glslang,
SPIR-V headers/tools and X11 development files. Then:

```sh
CC=clang CXX=clang++ ORDER1886_LTO=OFF ORDER1886_PGO=off CMAKE_BUILD_PARALLEL_LEVEL=4 bash build.sh --test
python3 -m venv out/linux-pyenv
out/linux-pyenv/bin/python -m pip install pyinstaller==6.20.0 pillow==12.3.0
out/linux-pyenv/bin/python packaging/linux/order1886-package.py
```

The output includes a hash manifest, native build receipt, dependency licenses and
archive checksum. Source/attribution: https://github.com/JulioCacko/The-Order-1886_pc
