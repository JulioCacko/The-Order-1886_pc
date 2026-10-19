// SPDX-FileCopyrightText: Copyright 2026 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include <algorithm>
#include <bit>
#include <limits>
#include <optional>
#include "video_core/renderer_vulkan/vk_common.h"
#include "video_core/texture_cache/image_rejection.h"
#include <vulkan/vulkan_format_traits.hpp>

namespace Vulkan {

/// The same decision VideoCore::ClassifyImageRequest makes, with the Vulkan limits filled
/// in. One implementation means the abort messages and the refusal path cannot disagree.
inline VideoCore::ImageRejection ClassifyImageCreateInfo(const vk::ImageCreateInfo& image,
                                                         const vk::ImageFormatProperties& limits) {
    VideoCore::ImageRequestLimits request{};
    request.width = image.extent.width;
    request.height = image.extent.height;
    request.depth = image.extent.depth;
    request.levels = image.mipLevels;
    request.layers = image.arrayLayers;
    request.max_width = limits.maxExtent.width;
    request.max_height = limits.maxExtent.height;
    request.max_depth = limits.maxExtent.depth;
    request.max_levels = limits.maxMipLevels;
    request.max_layers = limits.maxArrayLayers;
    request.samples_supported = bool(limits.sampleCounts & image.samples);
    return VideoCore::ClassifyImageRequest(request);
}

inline bool ImageFitsFormatLimits(const vk::ImageCreateInfo& image,
                                  const vk::ImageFormatProperties& limits) {
    return ClassifyImageCreateInfo(image, limits) == VideoCore::ImageRejection::None;
}

// Minimum byte span accessed by a copy, including padded rows/slices but excluding
// padding after its final copied row. All products must be checked before recording.
inline std::optional<u64> BufferImageCopyByteSize(const vk::BufferImageCopy& copy,
                                                 vk::Format format) {
    const auto block = vk::blockExtent(format);
    u64 block_size = vk::blockSize(format);
    if (copy.imageSubresource.aspectMask == vk::ImageAspectFlagBits::eStencil) {
        block_size = 1;
    } else if (copy.imageSubresource.aspectMask == vk::ImageAspectFlagBits::eDepth) {
        switch (format) {
        case vk::Format::eD16UnormS8Uint:
            block_size = 2;
            break;
        case vk::Format::eD24UnormS8Uint:
        case vk::Format::eD32SfloatS8Uint:
            block_size = 4;
            break;
        default:
            break;
        }
    }
    if (block_size == 0 || block[0] == 0 || block[1] == 0 || block[2] == 0 ||
        copy.imageExtent.width == 0 || copy.imageExtent.height == 0 ||
        copy.imageExtent.depth == 0 || copy.imageSubresource.layerCount == 0) {
        return std::nullopt;
    }
    const u64 row_length = copy.bufferRowLength ? copy.bufferRowLength : copy.imageExtent.width;
    const u64 height = copy.bufferImageHeight ? copy.bufferImageHeight : copy.imageExtent.height;
    if (row_length < copy.imageExtent.width || height < copy.imageExtent.height) {
        return std::nullopt;
    }
    const auto blocks = [](u64 pixels, u32 extent) { return (pixels + extent - 1) / extent; };
    constexpr u64 limit = std::numeric_limits<u64>::max();
    const auto multiply = [](u64 a, u64 b) -> std::optional<u64> {
        if (b != 0 && a > std::numeric_limits<u64>::max() / b) {
            return std::nullopt;
        }
        return a * b;
    };
    const auto row_pitch = multiply(blocks(row_length, block[0]), block_size);
    const auto slice_pitch = row_pitch ? multiply(blocks(height, block[1]), *row_pitch)
                                      : std::nullopt;
    const auto slices = multiply(blocks(copy.imageExtent.depth, block[2]),
                                 copy.imageSubresource.layerCount);
    const auto last_row = multiply(blocks(copy.imageExtent.width, block[0]), block_size);
    const auto rows_before = row_pitch ? multiply(blocks(copy.imageExtent.height, block[1]) - 1,
                                                  *row_pitch)
                                      : std::nullopt;
    const auto slices_before = slice_pitch && slices ? multiply(*slices - 1, *slice_pitch)
                                                   : std::nullopt;
    if (!last_row || !rows_before || !slices_before || *rows_before > limit - *last_row ||
        *slices_before > limit - (*rows_before + *last_row)) {
        return std::nullopt;
    }
    return *slices_before + *rows_before + *last_row;
}

inline bool BufferImageCopyFits(const vk::BufferImageCopy& copy, u64 copy_bytes,
                                u64 buffer_bytes) {
    return copy.bufferOffset <= buffer_bytes && copy_bytes <= buffer_bytes - copy.bufferOffset;
}

} // namespace Vulkan
