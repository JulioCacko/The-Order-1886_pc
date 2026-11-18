#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Build the Linux runtime (out/order1886-runtime, out/gpu/libps4gpu.so, out/order1886_fsr3.so) from
# this checkout. Adapted from DivinusX/a-port-of-the-order-1886-thats-actually-alive
# (packaging/linux/build-engine.sh, v0.2.33), which cloned JulioCacko/The-Order-1886_pc at
# 37482884 and applied its five engine patches first; those patches are now ordinary commits in
# this repository, so the clone-and-patch step is gone. NOT run on Linux by the author of this
# adaptation.
#
#   packaging/linux/build-engine.sh <work-dir>
#
# Needs: git, clang/gcc, cmake, ninja, pkg-config, glslang, curl, and the development packages
# Vulkan, SDL3, FFmpeg, fmt, Boost, robin-map, xxhash, X11 and Zydis (Arch:
# `pacman -S --needed boost robin-map zydis`; the rest is usually installed). VulkanMemoryAllocator
# is header-only and fetched into <work-dir>/deps when the system has none.
#
# The FSR 4 provider (out/order1886_fsr4.so) is not built here: its source (gpu/upscalers/fsr4/)
# was never published. Keep the module from the previous package; its ABI is the one this
# engine expects (build.sh skips providers whose source directory is absent).
set -euo pipefail

VMA_TAG=v3.5.0
REPO=$(cd -- "$(dirname -- "$0")/../.." && pwd)
WORK=$(realpath -m "${1:?usage: build-engine.sh <work-dir>}")
mkdir -p "$WORK"
cd "$REPO"
git submodule update --init --recursive --depth 1

# VulkanMemoryAllocator: CMake falls back to finding vk_mem_alloc.h (gpu/CMakeLists.txt).
include_path=()
if ! { [[ -f /usr/include/vk_mem_alloc.h ]] || [[ -f /usr/include/vma/vk_mem_alloc.h ]]; }; then
    mkdir -p "$WORK/deps/include/vma"
    [[ -f $WORK/deps/include/vma/vk_mem_alloc.h ]] || curl -fsSL -o "$WORK/deps/include/vma/vk_mem_alloc.h" \
        "https://raw.githubusercontent.com/GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator/$VMA_TAG/include/vk_mem_alloc.h"
    include_path=(CMAKE_INCLUDE_PATH="$WORK/deps/include")
fi

# GCC 16 rejects vk_pipeline_cache.cpp:508 (a member named like the lambda it names,
# -Wchanges-meaning); the code is correct, so the diagnostic is turned off rather than the code
# changed. build.sh stops at the missing FSR 4 provider, after the library and FSR 3 are built.
rm -f out/gpu/CMakeCache.txt
env "${include_path[@]}" CXXFLAGS="-Wno-changes-meaning" ORDER1886_PGO=off bash build.sh || true
[[ -f out/gpu/libps4gpu.so && -f out/order1886_fsr3.so ]] || { echo 'GPU library build failed: out/gpu-build.log' >&2; exit 1; }

# The rest of build.sh's Linux path: link the runtime against the library.
CC=$(command -v cc || command -v gcc)
read -r -a includes <<< "$(pkg-config --cflags vulkan sdl3 libavcodec libavutil libswscale)"
read -r -a libraries <<< "$(pkg-config --libs vulkan sdl3 libavcodec libavutil libswscale)"
if [[ ! -f out/libatrac9.a ]]; then
    rm -rf out/atrac9 && mkdir -p out/atrac9
    for source in third_party/LibAtrac9/C/src/*.c; do
        "$CC" -std=c99 -O2 -g -w -c "$source" -o "out/atrac9/$(basename "${source%.c}").o"
    done
    ar rcs out/libatrac9.a out/atrac9/*.o
fi
"$CC" -std=c11 -O2 -g -Wall -Wextra -Werror -mgeneral-regs-only -c src/isa_emulate.c -o out/isa_emulate.o
"$CC" -std=c11 -O2 -g -Wall -Wextra -Werror -pthread -no-pie "${includes[@]}" -I. -Isrc src/probe.c src/runtime*.c \
    src/cpu_check.c src/vulkan_smoke.c out/isa_emulate.o src/isa_rewrite.c out/libatrac9.a -lm \
    -Lout/gpu -lps4gpu -Wl,-rpath,'$ORIGIN/gpu' -rdynamic "${libraries[@]}" -o out/order1886-runtime
./out/order1886-runtime --runtime-info

cat <<EOF

Built from $REPO:
  $REPO/out/order1886-runtime     -> <package>/bin/order1886-runtime.bin
  $REPO/out/gpu/libps4gpu.so      -> <package>/bin/gpu/libps4gpu.so
  $REPO/out/order1886_fsr3.so     -> <package>/bin/order1886_fsr3.so
Strip them (strip --strip-debug), then run
  python3 packaging/linux/order1886-bundle.py fix   "<package>"
  python3 packaging/linux/order1886-bundle.py check "<package>"
EOF
