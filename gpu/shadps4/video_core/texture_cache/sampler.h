// SPDX-FileCopyrightText: Copyright 2024 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include <array>
#include <optional>

#include "video_core/amdgpu/regs_texture.h"
#include "video_core/amdgpu/resource.h"
#include "video_core/renderer_vulkan/vk_common.h"

namespace Vulkan {
class Instance;
}

namespace VideoCore {

class Sampler {
public:
    explicit Sampler(const Vulkan::Instance& instance, const AmdGpu::Sampler& sampler,
                     const std::optional<std::array<float, 4>>& custom_border_color, bool is_depth,
                     float extra_lod_bias = 0.0f);
    ~Sampler();

    Sampler(const Sampler&) = delete;
    Sampler& operator=(const Sampler&) = delete;

    Sampler(Sampler&&) = default;
    Sampler& operator=(Sampler&&) = default;

    vk::Sampler Handle() const noexcept {
        return *handle;
    }

    size_t lru_id{};

private:
    vk::UniqueSampler handle;
};

} // namespace VideoCore
