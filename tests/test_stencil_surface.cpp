// SPDX-License-Identifier: GPL-2.0-or-later
//
// A depth surface that also carries stencil needs a correctly sized stencil companion. This tree
// sized it as `pitch * height` — no layers, no tiling geometry, no multisampling — which truncated
// every layered, tiled or multisampled stencil surface. Upstream shadPS4 sizes it per slice from
// the tile geometry; `GetStencilSliceSize()` ports that, and this pins it.

#include <cassert>
#include <cstdio>
#include <cstdlib>

#include "video_core/amdgpu/regs_depth.h"

#include "common/logging/log.h"

// regs_depth.h asserts and logs; the other native tests stub those the same way.
void assert_fail_impl() { std::abort(); }
[[noreturn]] void unreachable_impl() { std::abort(); }
namespace Common::Log {
bool ShouldLog(Level) { return false; }
void Write(std::string_view, Level, const char*, int, const char*, std::string&&) {}
}


namespace {

AmdGpu::DepthBuffer MakeDepth(AmdGpu::DepthBuffer::StencilFormat stencil, u32 tile_max,
                              AmdGpu::DepthBuffer::ZFormat depth) {
    AmdGpu::DepthBuffer buffer{};
    buffer.z_info.format = depth;
    buffer.stencil_info.format = stencil;
    buffer.depth_slice.tile_max = tile_max;
    return buffer;
}

} // Anonymous namespace

int main() {
    using AmdGpu::DepthBuffer;

    // No stencil companion means no stencil surface to size.
    {
        auto buffer = MakeDepth(DepthBuffer::StencilFormat::Invalid, 0, DepthBuffer::ZFormat::Z32Float);
        if (buffer.GetStencilSliceSize() != 0) {
            std::puts("a depth-only surface must report no stencil slice");
            return EXIT_FAILURE;
        }

    }

    // A stencil companion is one byte per sample over the same tile geometry as the depth.
    {
        auto buffer = MakeDepth(DepthBuffer::StencilFormat::Stencil8, 3, DepthBuffer::ZFormat::Z32Float);
        const u32 slice = buffer.GetStencilSliceSize();
        const u32 expected = (3u + 1u) * 64u * 1u * buffer.GuestNumSamples();
        if (slice != expected) {
            std::printf("stencil slice %u != expected %u\n", slice, expected);
            return EXIT_FAILURE;
        }
        // Depth with the same geometry is wider, because it carries the depth bit width.
        if (buffer.GetDepthSliceSize() <= slice) {
            std::puts("a 32-bit depth slice must exceed the 8-bit stencil slice");
            return EXIT_FAILURE;
        }
    }

    // Multisampling multiplies both slices equally, so their ratio stays the depth width.
    {
        auto msaa = MakeDepth(DepthBuffer::StencilFormat::Stencil8, 1, DepthBuffer::ZFormat::Z32Float);
        msaa.z_info.num_samples = 2; // 4x on Orbis numbering
        const u32 stencil = msaa.GetStencilSliceSize();
        const u32 depth = msaa.GetDepthSliceSize();
        if (stencil == 0 || depth / stencil != 4) {
            std::printf("multisampled slices disagree: depth=%u stencil=%u\n", depth, stencil);
            return EXIT_FAILURE;
        }
    }

    // The tile geometry drives the size: a larger tile_max is a larger surface.
    {
        const auto small = MakeDepth(DepthBuffer::StencilFormat::Stencil8, 0, DepthBuffer::ZFormat::Z32Float);
        const auto large = MakeDepth(DepthBuffer::StencilFormat::Stencil8, 8, DepthBuffer::ZFormat::Z32Float);
        if (large.GetStencilSliceSize() <= small.GetStencilSliceSize()) {
            std::puts("the stencil slice must follow the tile geometry");
            return EXIT_FAILURE;
        }
    }

    std::puts("Stencil surface: sized per slice from the tile geometry, absent without a format");
    return EXIT_SUCCESS;
}
