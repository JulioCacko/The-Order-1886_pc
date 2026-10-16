#pragma once

#include <array>
#include <optional>
#include "common/types.h"
#include "video_core/amdgpu/pixel_format.h"

namespace Shader::Optimization {

// The existing uncompressed FMask model supplies two identity-mapping payload words.
// GFX6 FMask descriptors use explicit component selectors (Mesa ac_descriptors.c,
// ac_build_gfx6_fmask_descriptor); an output such as Z may select the first word.
inline std::optional<std::array<u32, 4>> FmaskIdentityTexel(const AmdGpu::CompMapping& mapping) {
    const std::array selectors{mapping.r, mapping.g, mapping.b, mapping.a};
    std::array<u32, 4> result{};
    for (size_t i = 0; i < result.size(); ++i) {
        switch (selectors[i]) {
        case AmdGpu::CompSwizzle::Zero: result[i] = 0; break;
        case AmdGpu::CompSwizzle::One: result[i] = 1; break;
        case AmdGpu::CompSwizzle::Red: result[i] = 0x76543210; break;
        case AmdGpu::CompSwizzle::Green: result[i] = 0xfedcba98; break;
        // shortcut: B/A need an established FMask payload before this model can support them.
        default: return std::nullopt;
        }
    }
    return result;
}

} // namespace Shader::Optimization
