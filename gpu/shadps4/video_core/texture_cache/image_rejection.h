// SPDX-FileCopyrightText: Copyright 2026 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include <algorithm>
#include <bit>
#include <cstdint>

namespace VideoCore {

/// Why a guest image descriptor cannot become a host image.
///
/// Every value except None corresponds to a place the renderer used to abort the whole
/// process (see image.cpp and image_info.cpp). Keeping the decision here means the
/// existing messages, and the refusal path that will replace them, agree on one
/// classification instead of each site re-deriving it.
enum class ImageRejection : uint8_t {
    None = 0,
    FormatQueryFailed,
    ExceedsFormatLimits,
    ProbeFailed,
    ExceedsResourceSize,
    GuestLayoutOverflow,
    InvalidGuestLayout,
    UnhandledArrayMode,
};

constexpr const char* DescribeImageRejection(ImageRejection rejection) {
    switch (rejection) {
    case ImageRejection::None:
        return "accepted";
    case ImageRejection::FormatQueryFailed:
        return "format query failed";
    case ImageRejection::ExceedsFormatLimits:
        return "exceeds device format limits";
    case ImageRejection::ProbeFailed:
        return "memory-requirement probe failed";
    case ImageRejection::ExceedsResourceSize:
        return "exceeds device resource size";
    case ImageRejection::GuestLayoutOverflow:
        return "exceeds guest layout capacity";
    case ImageRejection::InvalidGuestLayout:
        return "invalid guest image layout";
    case ImageRejection::UnhandledArrayMode:
        return "unhandled array mode";
    }
    return "unknown rejection";
}

/// The parts of a request that decide whether a host image may be created. Plain integers
/// so this decision can be tested without a device.
struct ImageRequestLimits {
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t depth = 0;
    uint32_t levels = 0;
    uint32_t layers = 0;
    uint32_t max_width = 0;
    uint32_t max_height = 0;
    uint32_t max_depth = 0;
    uint32_t max_levels = 0;
    uint32_t max_layers = 0;
    bool samples_supported = true;
    uint64_t required_bytes = 0;
    uint64_t max_resource_bytes = 0;
};

/// The format-limit decision, mirrored by Vulkan::ImageFitsFormatLimits.
constexpr ImageRejection ClassifyImageRequest(const ImageRequestLimits& request) {
    if (request.width == 0 || request.width > request.max_width) {
        return ImageRejection::ExceedsFormatLimits;
    }
    if (request.height == 0 || request.height > request.max_height) {
        return ImageRejection::ExceedsFormatLimits;
    }
    if (request.depth == 0 || request.depth > request.max_depth) {
        return ImageRejection::ExceedsFormatLimits;
    }
    if (request.levels == 0 || request.levels > request.max_levels) {
        return ImageRejection::ExceedsFormatLimits;
    }
    if (request.levels >
        uint32_t(std::bit_width(std::max({request.width, request.height, request.depth})))) {
        return ImageRejection::ExceedsFormatLimits;
    }
    if (request.layers == 0 || request.layers > request.max_layers) {
        return ImageRejection::ExceedsFormatLimits;
    }
    if (!request.samples_supported) {
        return ImageRejection::ExceedsFormatLimits;
    }
    if (request.required_bytes > request.max_resource_bytes) {
        return ImageRejection::ExceedsResourceSize;
    }
    return ImageRejection::None;
}

} // namespace VideoCore
