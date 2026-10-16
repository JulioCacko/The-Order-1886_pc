// SPDX-FileCopyrightText: Copyright 2026 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include <limits>
#include <optional>
#include "common/types.h"

namespace VideoCore {

// ImageInfo and the guest tiling paths currently store byte offsets and sizes as u32.
// Reject a layout before narrowing it; wrapping can turn a large mip into a zero-sized upload.
constexpr std::optional<u32> GuestMipSize(u64 slice_bytes, u32 depth, u32 layers,
                                         u32 bytes_before = 0) {
    constexpr u64 limit = std::numeric_limits<u32>::max();
    if (slice_bytes == 0 || depth == 0 || layers == 0 || slice_bytes > limit ||
        depth > limit / slice_bytes) {
        return std::nullopt;
    }
    const u64 volume_bytes = slice_bytes * depth;
    if (layers > (limit - bytes_before) / volume_bytes) {
        return std::nullopt;
    }
    return static_cast<u32>(volume_bytes * layers);
}

} // namespace VideoCore
