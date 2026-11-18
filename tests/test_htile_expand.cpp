// SPDX-License-Identifier: GPL-2.0-or-later
// Deterministic checks for the HTILE uncompressed-mask range (htile_expand.h), the half of
// theorder1886-port#26 that restores sun shadows and wet-surface specular on RDNA4.
#include "video_core/renderer_vulkan/htile_expand.h"

#include <cassert>
#include <cstdio>

int main() {
    using VideoCore::HtileUncompressedSize;
    // The sun cascade maps: 1024x1024 with 2 layers is exactly what the RX 9070 XT boot log
    // reported as "marked uncompressed, 131072 bytes".
    assert(HtileUncompressedSize(1024, 1024, 2) == 131072);
    // One u32 per 8x8 tile, the tile grid padded to whole 64-tile rows.
    assert(HtileUncompressedSize(8, 8, 1) == 64 * 64 * 4);
    assert(HtileUncompressedSize(1920, 1080, 1) == 256u * 192u * 4);
    // Layer count 0 behaves like 1; a zero extent covers nothing.
    assert(HtileUncompressedSize(1024, 1024, 0) == 65536);
    assert(HtileUncompressedSize(0, 0, 1) == 0);
    // The main depth buffer at 16:9 4K: (3840/8=480 -> 512 rows, 2160/8=270 -> 320 rows).
    assert(HtileUncompressedSize(3840, 2160, 1) == 512u * 320u * 4);
    std::puts("htile expand range checks passed");
    return 0;
}
