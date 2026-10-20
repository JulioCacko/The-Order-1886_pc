// SPDX-License-Identifier: GPL-2.0-or-later
//
// Upstream shadPS4 maps a guest cube descriptor to a 2D image; this project did not, so a cube
// image reached the `default:` branch of the conversion and aborted the process. That is the same
// shape as the array-layer crash: a descriptor the emulator had not been taught yet killing the
// session instead of being handled. These checks keep the mapping complete and keep the "is it
// mapped" answer derived from the mapping itself.

#include <cstdio>
#include <cstdlib>
#include <optional>
#include <string_view>

#include "video_core/texture_cache/image_type_map.h"

using AmdGpu::ImageType;
using VideoCore::ConvertImageType;
using VideoCore::IsMappedImageType;
using VideoCore::OptionalImageType;

namespace {

int fail(std::string_view message) {
    std::printf("%.*s\n", static_cast<int>(message.size()), message.data());
    return EXIT_FAILURE;
}

} // Anonymous namespace

int main() {
    // Shapes this project has never bound are refused explicitly, not by accident.
    constexpr ImageType refused[] = {ImageType::Invalid, ImageType::Color2DMsaaArray};
    constexpr ImageType mapped[] = {
        ImageType::Color1D,     ImageType::Color1DArray, ImageType::Color2D,
        ImageType::Color2DMsaa, ImageType::Color2DArray,  ImageType::Color3D,
        ImageType::Cube,
    };

    for (const auto type : mapped) {
        if (!OptionalImageType(type).has_value()) {
            return fail("a guest image shape lost its mapping");
        }
        if (!IsMappedImageType(type)) {
            return fail("IsMappedImageType disagrees with the mapping switch");
        }
    }
    for (const auto type : refused) {
        if (OptionalImageType(type).has_value() || IsMappedImageType(type)) {
            return fail("a refused shape must report no mapping");
        }
    }

    // A cube is six 2D array layers on the host, which is upstream's mapping.
    if (ConvertImageType(ImageType::Cube) != vk::ImageType::e2D) {
        return fail("Cube must map to a 2D image");
    }
    if (ConvertImageType(ImageType::Color2DArray) != vk::ImageType::e2D ||
        ConvertImageType(ImageType::Color2DMsaa) != vk::ImageType::e2D) {
        return fail("Array and multisample shapes must map to a 2D image");
    }
    if (ConvertImageType(ImageType::Color1D) != vk::ImageType::e1D ||
        ConvertImageType(ImageType::Color3D) != vk::ImageType::e3D) {
        return fail("1D and 3D shapes must keep their own image type");
    }

    std::puts("Image type mapping: every guest shape maps or is refused, never aborts");
    return EXIT_SUCCESS;
}
