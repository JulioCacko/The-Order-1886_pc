// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once

#include <limits>
#include "common/types.h"
#include "shader_recompiler/resource.h"
#include "shader_recompiler/runtime_info.h"

namespace Vulkan {

constexpr bool UsesOrderImageModeGuard(const auto& stage) {
    return stage.pgm_hash == 0xa7b66f58 && stage.hw_stage == Shader::HwStage::Compute;
}

// shortcut: this contract covers the verified a7b66f58 shader only; require fresh IR/GCN
// dominance evidence before extending it. Every image sample requires record mode == 3.
bool IsOrderComputeImageInactive(const auto& stage, u32 image_index, auto&& read_coherent_mode,
                                bool bound_ring_snapshot = false) {
    if (bound_ring_snapshot || !UsesOrderImageModeGuard(stage) || image_index != 0 || stage.images.size() != 1 ||
        stage.buffers.size() < 2) {
        return false;
    }
    const auto& image = stage.images[0];
    const auto& source = stage.buffers[1];
    const auto flat = stage.FlatUserData();
    if (flat.size() <= 52 || image.is_written || image.is_atomic || image.is_depth ||
        image.is_r128 || image.declared_binding_count != 1 ||
        image.post_op != Shader::SharpFetchPostOp::None ||
        image.mip_fallback_mode != Shader::MipStorageFallbackMode::None ||
        image.sharp_fetch.load_mask != 0xff || source.sharp_fetch.load_mask != 0xf ||
        source.IsSpecial() || source.is_written || source.buffer_type != Shader::BufferType::Guest ||
        source.post_op != Shader::SharpFetchPostOp::None) {
        return false;
    }
    for (u32 i = 0; i < 8; ++i) {
        if (image.sharp_fetch.offsets[i] != 44 + i) return false;
    }
    for (u32 i = 0; i < 4; ++i) {
        if (source.sharp_fetch.offsets[i] != 16 + i) return false;
    }
    const auto buffer = source.GetSharp(stage);
    // Match the guest's 32-bit multiply/add before converting DWORDs to bytes.
    const u32 word_offset = ((flat[52] * 1020u + 196u) >> 2) + 1u;
    const u64 offset = u64(word_offset) * sizeof(u32);
    const u64 size = buffer.GetSize();
    const u64 base = buffer.base_address;
    if (offset > size || size - offset < sizeof(u32) ||
        base > std::numeric_limits<u64>::max() - offset - (sizeof(u32) - 1)) {
        return false;
    }
    const auto mode = read_coherent_mode(base + offset);
    return mode.has_value() && *mode != 3;
}

} // namespace Vulkan
