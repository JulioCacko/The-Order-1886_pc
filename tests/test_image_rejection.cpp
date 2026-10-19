// SPDX-FileCopyrightText: Copyright 2026 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

// The decision that used to abort the process is now expressed once, in
// image_rejection.h, and this test fixes its behaviour. The 8029-layer case that kills
// the title must classify as a format-limit rejection, not as an accepted request and
// not as something the callers have to discover by crashing.
#undef NDEBUG
#include "../gpu/shadps4/video_core/texture_cache/image_rejection.h"

#include <cassert>
#include <cstddef>
#include <cstring>
#include <iterator>

using VideoCore::ClassifyImageRequest;
using VideoCore::DescribeImageRejection;
using VideoCore::ImageRejection;
using VideoCore::ImageRequestLimits;

namespace {

ImageRequestLimits Accepted() {
    ImageRequestLimits request{};
    request.width = 1920;
    request.height = 1080;
    request.depth = 1;
    request.levels = 1;
    request.layers = 1;
    request.max_width = 16384;
    request.max_height = 16384;
    request.max_depth = 2048;
    request.max_levels = 16;
    request.max_layers = 2048;
    request.samples_supported = true;
    request.required_bytes = 8 << 20;
    request.max_resource_bytes = 1ull << 33;
    return request;
}

} // namespace

int main() {
    assert(ClassifyImageRequest(Accepted()) == ImageRejection::None);

    // The reported crash: an array image whose decoded depth produced 8029 layers.
    auto oversized = Accepted();
    oversized.layers = 8029;
    assert(ClassifyImageRequest(oversized) == ImageRejection::ExceedsFormatLimits);

    // The boundary itself is accepted, one past it is not.
    auto limit = Accepted();
    limit.layers = 2048;
    assert(ClassifyImageRequest(limit) == ImageRejection::None);
    limit.layers = 2049;
    assert(ClassifyImageRequest(limit) == ImageRejection::ExceedsFormatLimits);

    auto zero_layers = Accepted();
    zero_layers.layers = 0;
    assert(ClassifyImageRequest(zero_layers) == ImageRejection::ExceedsFormatLimits);

    auto wide = Accepted();
    wide.width = 16385;
    assert(ClassifyImageRequest(wide) == ImageRejection::ExceedsFormatLimits);

    auto tall = Accepted();
    tall.height = 0;
    assert(ClassifyImageRequest(tall) == ImageRejection::ExceedsFormatLimits);

    auto deep = Accepted();
    deep.depth = 4096;
    assert(ClassifyImageRequest(deep) == ImageRejection::ExceedsFormatLimits);

    auto levels = Accepted();
    levels.levels = 17;
    assert(ClassifyImageRequest(levels) == ImageRejection::ExceedsFormatLimits);

    // A small extent cannot carry many mip levels even when the device allows them.
    auto too_many_levels = Accepted();
    too_many_levels.width = 4;
    too_many_levels.height = 4;
    too_many_levels.levels = 8;
    assert(ClassifyImageRequest(too_many_levels) == ImageRejection::ExceedsFormatLimits);

    auto samples = Accepted();
    samples.samples_supported = false;
    assert(ClassifyImageRequest(samples) == ImageRejection::ExceedsFormatLimits);

    auto huge = Accepted();
    huge.required_bytes = (1ull << 33) + 1;
    assert(ClassifyImageRequest(huge) == ImageRejection::ExceedsResourceSize);

    // The binding path refuses an impossible array size instead of aborting: the same decision
    // image creation used, expressed where a null binding is already a supported state.
    assert(VideoCore::ExceedsArrayLayerLimit(8029, 2048));
    assert(!VideoCore::ExceedsArrayLayerLimit(2048, 2048));
    assert(VideoCore::ExceedsArrayLayerLimit(2049, 2048));
    assert(VideoCore::ExceedsArrayLayerLimit(0, 2048));
    assert(VideoCore::MinArrayLayers == 256);
    // Classification is reported, and every value has a distinct name for the log.
    assert(std::strcmp(DescribeImageRejection(ImageRejection::None), "accepted") == 0);
    const char* names[] = {
        DescribeImageRejection(ImageRejection::FormatQueryFailed),
        DescribeImageRejection(ImageRejection::ExceedsFormatLimits),
        DescribeImageRejection(ImageRejection::ProbeFailed),
        DescribeImageRejection(ImageRejection::ExceedsResourceSize),
        DescribeImageRejection(ImageRejection::GuestLayoutOverflow),
        DescribeImageRejection(ImageRejection::InvalidGuestLayout),
        DescribeImageRejection(ImageRejection::UnhandledArrayMode),
    };
    for (std::size_t i = 0; i < std::size(names); ++i) {
        assert(names[i] != nullptr && names[i][0] != '\0');
        for (std::size_t j = i + 1; j < std::size(names); ++j) {
            assert(std::strcmp(names[i], names[j]) != 0);
        }
    }
    return 0;
}
