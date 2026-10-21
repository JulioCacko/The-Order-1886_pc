// SPDX-License-Identifier: GPL-2.0-or-later
// Temporal input probe for The Order (#7, docs/order1886-frame-map.md).
#pragma once

#include <span>
#include "common/types.h"
#include "video_core/texture_cache/types.h"

namespace Vulkan {

class Rasterizer;

/// The Order's own temporal resolve: MSAA scene color, velocity, history and exposure in.
inline constexpr u64 OrderTemporalResolveHash = 0x92311aca;

/// ORDER1886_TEMPORAL_PROBE=1: after the game's temporal resolve, measure whether its velocity
/// predicts the previous frame (host_shaders/temporal_probe.comp) and log the result.
bool TemporalProbeEnabled();

/// `images`: the images the resolve dispatch bound. Leaves the game's own work untouched.
void RunTemporalProbe(Rasterizer& rasterizer, std::span<const VideoCore::ImageId> images);

} // namespace Vulkan
