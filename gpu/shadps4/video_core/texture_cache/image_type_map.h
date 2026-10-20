// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once

// Guest image type -> Vulkan image type.
//
// This mirrors the mapping in upstream shadPS4 (GPL-2.0-or-later), which is where the `Cube`
// case comes from. Ours lacked it, so a guest cube descriptor reached the `default:` branch and
// aborted the process — the same failure shape as the image-layer crash, for a descriptor shape
// the emulator had not been taught yet. A cube texture is a 2D array on the host, so the mapping
// is one line.
//
// The switch is the single source of truth: `IsMappedImageType` is derived from it rather than
// maintained beside it, so a shape cannot be "declared supported" while silently falling through.

#include <optional>

#include "video_core/amdgpu/resource.h"
#include "video_core/renderer_vulkan/vk_common.h"

namespace VideoCore {

constexpr std::optional<vk::ImageType> OptionalImageType(AmdGpu::ImageType type) {
    switch (type) {
    case AmdGpu::ImageType::Color1D:
    case AmdGpu::ImageType::Color1DArray:
        return vk::ImageType::e1D;
    case AmdGpu::ImageType::Color2D:
    case AmdGpu::ImageType::Color2DMsaa:
    case AmdGpu::ImageType::Color2DArray:
    // A cube is six array layers of a 2D image on the host.
    case AmdGpu::ImageType::Cube:
        return vk::ImageType::e2D;
    case AmdGpu::ImageType::Color3D:
        return vk::ImageType::e3D;
    default:
        return std::nullopt;
    }
}

constexpr bool IsMappedImageType(AmdGpu::ImageType type) {
    return OptionalImageType(type).has_value();
}

constexpr vk::ImageType ConvertImageType(AmdGpu::ImageType type) {
    // Callers check IsMappedImageType first; e2D is the harmless fallback for a diagnostic path.
    return OptionalImageType(type).value_or(vk::ImageType::e2D);
}

} // namespace VideoCore
