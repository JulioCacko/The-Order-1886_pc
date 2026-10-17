"""CPU regressions for production image layout and Vulkan transfer bounds."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.test_order1886_srt_codegen import function_body


ROOT = Path(__file__).resolve().parents[1]


class ImageBoundsTests(unittest.TestCase):
    def test_runtime_image_upload_rejects_bad_footprints_before_recording_or_cleaning(self):
        runtime = (ROOT / "gpu/shadps4/video_core/renderer_vulkan/vk_runtime.cpp").read_text()
        upload = function_body(runtime, "void Runtime::UploadImage(")
        check = upload.index("BufferImageCopyFits(copy, copy_size, src->SizeBytes())")
        self.assertLess(check, upload.index("scheduler.Record("))
        self.assertLess(check, upload.index("dst->flags &= ~VideoCore::ImageFlagBits::Dirty"))
        self.assertIn("Image upload exceeds source buffer", upload)

    def test_checked_layout_device_limits_and_upload_footprints(self):
        source = (ROOT / "gpu/shadps4/video_core/texture_cache/image_info.cpp").read_text()
        update_size = function_body(source, "void ImageInfo::UpdateSize(")
        tiling = (ROOT / "gpu/shadps4/video_core/amdgpu/tiling.cpp").read_text()
        tiling_functions = (function_body(tiling, "bool IsMacroTiled(") + "\n" +
                            function_body(tiling, "u32 GetMicroTileThickness("))
        harness = r'''
#include <atomic>
#include <bit>
#include <cassert>
#include <stdexcept>
#include "video_core/texture_cache/image_info.h"
#include "video_core/texture_cache/image_size.h"
#include "video_core/renderer_vulkan/vk_image_bounds.h"
#include "common/assert.h"
#undef ASSERT
#undef UNREACHABLE_MSG
#define ASSERT(condition) do { if (!(condition)) throw std::runtime_error("assert: " #condition); } while (false)
#define UNREACHABLE_MSG(...) throw std::runtime_error(fmt::format(__VA_ARGS__))
#include "video_core/texture_cache/tile.h"
namespace AmdGpu {
''' + tiling_functions + r'''
}
namespace VideoCore {
static void LogResourceSharp(const AmdGpu::Image&, const Shader::ImageResource&, u32, const char*) {}
''' + update_size + r'''
}
int main() {
    using namespace VideoCore;
    using namespace Vulkan;
    constexpr u32 limit = std::numeric_limits<u32>::max();
    assert(GuestMipSize(1024, 1, 6) == 6144);
    assert(GuestMipSize(limit, 1, 1) == limit);
    assert(!GuestMipSize(4194304, 1, 4096)); // observed 16 GiB mip
    assert(!GuestMipSize(1073741824, 1, 4)); // exactly 4 GiB cannot narrow
    assert(!GuestMipSize(1024, 1, 1, limit - 1023)); // cumulative overflow
    assert(!GuestMipSize(std::numeric_limits<u64>::max(), 2, 2));
    assert(!GuestMipSize(0, 1, 1));
    assert(!GuestMipSize(1, 0, 1));
    assert(!GuestMipSize(1, 1, 0));
    assert(std::get<2>(ImageSizeLinearAligned(65536, 16384, 128, 16)) == 274877906944ull);
    assert(std::get<2>(ImageSizeMicroTiled(65536, 16384, 1, 128, 16)) == 274877906944ull);
    assert(std::get<2>(ImageSizeMacroTiled(65536, 16384, 1, 32, 1,
                                        AmdGpu::TileMode::Display2DThin, 0, false)) == 4294967296ull);

    ImageInfo info{};
    info.pitch = 16384;
    info.size = {256, 256, 1};
    info.props.is_block = true;
    info.num_bits = 128;
    info.resources = {9, 4096};
    bool rejected = false;
    try { info.UpdateSize(); } catch (const std::runtime_error&) { rejected = true; }
    assert(rejected && info.guest_size == 0);
    info.pitch = 256;
    info.resources = {9, 8};
    info.UpdateSize();
    assert(info.mips_layout[0].size == 524288);
    assert(info.mips_layout[1].offset == 524288);
    assert(info.guest_size > info.mips_layout[0].size);

    vk::BufferImageCopy copy{};
    copy.bufferRowLength = 16384;
    copy.bufferImageHeight = 256;
    copy.imageExtent = vk::Extent3D{256, 256, 1};
    copy.imageSubresource.layerCount = 4096;
    copy.imageSubresource.aspectMask = vk::ImageAspectFlagBits::eColor;
    const auto bytes = BufferImageCopyByteSize(copy, vk::Format::eBc6HUfloatBlock);
    assert(bytes == 17179804672ull);
    assert(!BufferImageCopyFits(copy, *bytes, 1610612736));
    assert(BufferImageCopyFits(copy, *bytes, *bytes));
    copy.bufferOffset = std::numeric_limits<u64>::max() - 1;
    assert(!BufferImageCopyFits(copy, *bytes, std::numeric_limits<u64>::max()));
    copy = {};
    copy.imageExtent = vk::Extent3D{1, 1, 1};
    copy.imageSubresource.layerCount = 1;
    assert(BufferImageCopyByteSize(copy, vk::Format::eBc6HUfloatBlock) == 16);
    copy.imageExtent = vk::Extent3D{5, 5, 1};
    assert(BufferImageCopyByteSize(copy, vk::Format::eBc6HUfloatBlock) == 64);
    copy.imageExtent = vk::Extent3D{2, 2, 1};
    copy.imageSubresource.aspectMask = vk::ImageAspectFlagBits::eDepth;
    assert(BufferImageCopyByteSize(copy, vk::Format::eD32SfloatS8Uint) == 16);
    copy.imageSubresource.aspectMask = vk::ImageAspectFlagBits::eStencil;
    assert(BufferImageCopyByteSize(copy, vk::Format::eD32SfloatS8Uint) == 4);
    copy.imageExtent.width = 0;
    assert(!BufferImageCopyByteSize(copy, vk::Format::eR8G8B8A8Unorm));
    copy.imageExtent = vk::Extent3D{limit, limit, limit};
    copy.imageSubresource.layerCount = limit;
    copy.imageSubresource.aspectMask = vk::ImageAspectFlagBits::eColor;
    assert(!BufferImageCopyByteSize(copy, vk::Format::eR32G32B32A32Sfloat));

    vk::ImageFormatProperties limits{};
    limits.maxExtent = vk::Extent3D{16384, 16384, 2048};
    limits.maxMipLevels = 15;
    limits.maxArrayLayers = 2048;
    limits.sampleCounts = vk::SampleCountFlagBits::e1;
    vk::ImageCreateInfo image{};
    image.extent = vk::Extent3D{256, 256, 1};
    image.mipLevels = 9;
    image.arrayLayers = 4096;
    image.samples = vk::SampleCountFlagBits::e1;
    assert(!ImageFitsFormatLimits(image, limits));
    image.arrayLayers = 2048;
    assert(ImageFitsFormatLimits(image, limits));
    image.mipLevels = 16;
    assert(!ImageFitsFormatLimits(image, limits));
    image.mipLevels = 9;
    image.extent.width = 16385;
    assert(!ImageFitsFormatLimits(image, limits));
}
'''
        environment = os.environ.copy()
        compiler = shutil.which(environment.get("CXX", "clang++"))
        if os.name == "nt" and compiler is None:
            candidate = Path(environment.get("MSYS2_ROOT", r"C:\msys64")) / "clang64/bin/clang++.exe"
            if candidate.is_file():
                compiler = str(candidate)
        self.assertIsNotNone(compiler, "clang++ is required for the image bounds CPU regression")
        environment["PATH"] = str(Path(compiler).parent) + os.pathsep + environment.get("PATH", "")
        with tempfile.TemporaryDirectory(prefix="order1886-image-bounds-") as directory:
            cpp = Path(directory) / "image_bounds.cpp"
            exe = Path(directory) / ("image_bounds.exe" if os.name == "nt" else "image_bounds")
            cpp.write_text(harness, encoding="utf-8")
            subprocess.run([compiler, "-std=c++23", "-O2", "-UNDEBUG", "-DNOMINMAX",
                            "-DWIN32_LEAN_AND_MEAN", "-Wall", "-Wextra", "-Werror",
                            "-I" + str(ROOT / "gpu/shim"),
                            "-I" + str(ROOT / "gpu/shadps4"),
                            "-I" + str(ROOT / "gpu/third_party/magic_enum/include/magic_enum"),
                            str(cpp), "-lfmt", "-o", str(exe)], check=True, env=environment)
            subprocess.run([str(exe)], check=True, env=environment)


if __name__ == "__main__":
    unittest.main()
