// SPDX-FileCopyrightText: Copyright 2025 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include <atomic>
#include <cstdlib>
#include <optional>
#include <type_traits>
#include "common/assert.h"
#include "common/types.h"
#include "shader_recompiler/ir/type.h"
#include "video_core/amdgpu/resource.h"

#include <boost/container/static_vector.hpp>

namespace Shader {

static constexpr u32 NUM_USER_DATA_REGS = 16;
static constexpr u32 NUM_IMAGES = 64;
static constexpr u32 NUM_BUFFERS = 40;
static constexpr u32 NUM_SAMPLERS = 16;
static constexpr u32 NUM_FMASKS = 8;

using SharpLocation = u16;

constexpr SharpLocation UNKNOWN_LOCATION = std::numeric_limits<u16>::max();

template <typename T>
struct SharpFetch {
    static constexpr std::size_t N = sizeof(T) / sizeof(u32);
    static_assert(N <= 8);

    std::array<u32, N> immediates;
    std::array<SharpLocation, N> offsets;
    u8 load_mask;

    bool operator==(const SharpFetch&) const = default;

    template <u32 num_dwords = sizeof(T) / sizeof(u32)>
    [[nodiscard]] constexpr std::optional<u32> UnresolvedDword(size_t flatbuf_dwords) const {
        static_assert(num_dwords <= sizeof(T) / sizeof(u32));
        for (u32 i = 0; i < num_dwords; ++i) {
            if (((load_mask >> i) & 1) &&
                (offsets[i] == UNKNOWN_LOCATION || offsets[i] >= flatbuf_dwords)) {
                return i;
            }
        }
        return std::nullopt;
    }

    template <u32 num_dwords = N>
        requires(num_dwords <= N)
    constexpr bool Fetch(const u32* flatbuf, T* out) const {
        u8 mask = load_mask;
        for (u32 i = 0; i < num_dwords; i++) {
            if (((load_mask >> i) & 1) && offsets[i] == UNKNOWN_LOCATION) {
                return false;
            }
        }
        std::array<u32, num_dwords> out_dw;
        for (u32 i = 0; i < num_dwords; i++) {
            out_dw[i] = (mask & 1) ? flatbuf[offsets[i]] : immediates[i];
            mask >>= 1;
        }
        std::memcpy(out, out_dw.data(), sizeof(out_dw));
        return true;
    }
};

template <u32 num_dwords, typename T>
constexpr void RequireResolvedSharpSource(const auto& info, const char* kind,
                                          const SharpFetch<T>& fetch) {
    const auto flatbuf = info.FlatUserData();
    if (const auto missing = fetch.template UnresolvedDword<num_dwords>(flatbuf.size())) {
        if constexpr (requires { info.pgm_hash; info.hw_stage; }) {
            LOG_ERROR(Render_Recompiler,
                      "Unresolved {} descriptor: shader={:#018x} stage={} dword={} "
                      "location={} flat_size={} load_mask={:#x} locations={}",
                      kind, info.pgm_hash, info.hw_stage, *missing, fetch.offsets[*missing],
                      flatbuf.size(), fetch.load_mask, fetch.offsets);
        }
        UNREACHABLE_MSG("Cannot bind {} descriptor: dword {} has an unknown or out-of-range "
                        "SRT source (location {}, flat size {})",
                        kind, *missing, fetch.offsets[*missing], flatbuf.size());
    }
}

inline void TraceImageSharp(const auto& info, const SharpFetch<AmdGpu::Image>& fetch,
                           const AmdGpu::Image& image, bool r128) {
    static const bool enabled = [] {
        const char* value = std::getenv("ORDER1886_DIAG_RESOURCE_SHARPS");
        return value && value[0] == '1';
    }();
    if (!enabled) return;
    const auto data_format = static_cast<AmdGpu::DataFormat>(image.data_format);
    const bool packed_context = data_format == AmdGpu::DataFormat::FormatBG_RG ||
                                data_format == AmdGpu::DataFormat::FormatGB_GR;
    // Keep packed-format failure context available after ordinary tracing is exhausted.
    static std::atomic<u32> records{0}, packed_records{0};
    auto& budget = packed_context ? packed_records : records;
    const u32 limit = packed_context ? 16 : 512;
    u32 record = budget.load(std::memory_order_relaxed);
    do {
        if (record >= limit) return;
    } while (!budget.compare_exchange_weak(record, record + 1, std::memory_order_relaxed));
    std::array<u32, 8> raw{};
    std::memcpy(raw.data(), &image, sizeof(image));
    if constexpr (requires { info.pgm_hash; info.hw_stage; }) {
        LOG_WARNING(Render_Recompiler,
                    "Image sharp fetch: resource={} packed_context={} shader={:#018x} stage={} "
                    "r128={} load_mask={:#x} "
                    "locations={} raw={:08x} {:08x} {:08x} {:08x} "
                    "{:08x} {:08x} {:08x} {:08x}",
                    fmt::ptr(&fetch), packed_context, info.pgm_hash, info.hw_stage, r128,
                    fetch.load_mask, fetch.offsets,
                    raw[0], raw[1], raw[2], raw[3], raw[4], raw[5], raw[6], raw[7]);
    } else {
        LOG_WARNING(Render_Recompiler,
                    "Image sharp fetch: source_type={} resource={} packed_context={} "
                    "r128={} load_mask={:#x} locations={} raw={:08x} {:08x} {:08x} {:08x} "
                    "{:08x} {:08x} {:08x} {:08x}",
                    __PRETTY_FUNCTION__, fmt::ptr(&fetch), packed_context, r128, fetch.load_mask,
                    fetch.offsets, raw[0], raw[1], raw[2], raw[3], raw[4], raw[5], raw[6], raw[7]);
    }
}

enum class SharpFetchPostOp : u8 {
    None,
    // For buffers
    BitwiseOrDw1WithImm,
    OffsetByProgramBase,
    // For images,
    ConvertCubeTo2DArray,
    // For samplers
    DisableAnisoIfSingleLod,
    ForceRepeatXyzClamp,
    ForceLastTexelXyClamp,
    ClearAnisoRatioAndThreshold,
};

enum class BufferType : u8 {
    Guest,
    Flatbuf,
    BdaPagetable,
    FaultBuffer,
    GdsBuffer,
    SharedMemory,
    ClipPlanes,
};

struct BufferResource {
    SharpFetch<AmdGpu::Buffer> sharp_fetch{};
    IR::Type used_types{};
    BufferType buffer_type{};
    bool is_written{};
    bool is_formatted{};
    SharpFetchPostOp post_op{};
    u32 post_op_dw1_mask{};

    bool IsSpecial() const noexcept {
        return buffer_type != BufferType::Guest;
    }

    constexpr AmdGpu::Buffer GetSharp(const auto& info) const noexcept {
        AmdGpu::Buffer buffer;
        RequireResolvedSharpSource<4>(info, "buffer", sharp_fetch);
        if (!sharp_fetch.Fetch(info.FlatUserData().data(), &buffer)) {
            UNREACHABLE_MSG("Validated buffer descriptor fetch failed");
        }
        if (post_op == SharpFetchPostOp::BitwiseOrDw1WithImm) {
            reinterpret_cast<u32*>(&buffer)[1] |= post_op_dw1_mask;
        } else if (post_op == SharpFetchPostOp::OffsetByProgramBase) {
            buffer.base_address += info.ProgramBase();
        }
        if (!buffer.Valid()) {
            return AmdGpu::Buffer::Null();
        }
        return buffer;
    }
};
using BufferResourceList = boost::container::static_vector<BufferResource, NUM_BUFFERS>;

enum class MipStorageFallbackMode : u16 {
    None,
    DynamicIndex,
    ConstantIndex,
};

struct ImageResource {
    SharpFetch<AmdGpu::Image> sharp_fetch{};
    bool is_depth{};
    bool is_atomic{};
    bool is_array{};
    bool is_written{};
    bool is_r128{};
    /// read other than by normalized sampling without offsets (texel loads, size
    /// queries, offsets): needs the native-size image, not a reduced scene proxy.
    bool needs_native{};
    u8 constant_mip_index{};
    MipStorageFallbackMode mip_fallback_mode{};
    SharpFetchPostOp post_op{};

    constexpr AmdGpu::Image GetSharp(const auto& info) const noexcept {
        AmdGpu::Image image{};
        if (is_r128) {
            RequireResolvedSharpSource<4>(info, "image-r128", sharp_fetch);
        } else {
            RequireResolvedSharpSource<8>(info, "image", sharp_fetch);
        }
        if (!Fetch(info.FlatUserData().data(), &image)) {
            UNREACHABLE_MSG("Validated image descriptor fetch failed");
        }
        if (!std::is_constant_evaluated()) TraceImageSharp(info, sharp_fetch, image, is_r128);
        if (post_op == SharpFetchPostOp::ConvertCubeTo2DArray) {
            image.type = u64(AmdGpu::ImageType::Color2DArray);
            image.depth = (image.depth + 1) * 6 - 1;
        }
        if (!image.Valid()) {
            image = AmdGpu::Image::Null(is_depth);
        } else if (is_depth) {
            const auto data_fmt = image.GetDataFmt();
            if (data_fmt != AmdGpu::DataFormat::Format16 &&
                data_fmt != AmdGpu::DataFormat::Format32) {
                image = AmdGpu::Image::Null(true);
            }
        }
        return image;
    }

    constexpr bool Fetch(const u32* flatbuf, AmdGpu::Image* out) const {
        if (!is_r128) {
            // Fetch full 8 byte T#
            return sharp_fetch.Fetch(flatbuf, out);
        }
        // Fetch r128 T# and fix pitch
        if (!sharp_fetch.Fetch<4>(flatbuf, out)) {
            return false;
        }
        out->pitch = out->width;
        return true;
    }

    u32 NumBindingsFromSharp(const AmdGpu::Image& tsharp) const {
        return (mip_fallback_mode == MipStorageFallbackMode::DynamicIndex)
                   ? (tsharp.last_level - tsharp.base_level + 1)
                   : 1;
    }

    u32 NumBindings(const auto& info) const {
        return NumBindingsFromSharp(GetSharp(info));
    }
};
using ImageResourceList = boost::container::static_vector<ImageResource, NUM_IMAGES>;

struct SamplerResource {
    SharpFetch<AmdGpu::Sampler> sharp_fetch{};
    SharpFetchPostOp post_op{};
    SharpLocation post_op_tsharp_dw3_off{};
    bool is_depth{};

    constexpr AmdGpu::Sampler GetSharp(const auto& info) const noexcept {
        AmdGpu::Sampler sampler{};
        RequireResolvedSharpSource<4>(info, "sampler", sharp_fetch);
        if (!sharp_fetch.Fetch(info.FlatUserData().data(), &sampler)) {
            UNREACHABLE_MSG("Validated sampler descriptor fetch failed");
        }
        if (post_op == SharpFetchPostOp::DisableAnisoIfSingleLod) {
            SharpFetch<u32> lod_source{};
            lod_source.load_mask = 1;
            lod_source.offsets[0] = post_op_tsharp_dw3_off;
            RequireResolvedSharpSource<1>(info, "sampler LOD dependency", lod_source);
            const u32 tsharp_dw3 = info.FlatUserData()[post_op_tsharp_dw3_off];
            if (((tsharp_dw3 >> 12) & 0xff) == 0) {
                sampler.max_aniso.Assign(AmdGpu::AnisoRatio::One);
            }
        } else if (post_op == SharpFetchPostOp::ForceRepeatXyzClamp) {
            sampler.clamp_x.Assign(AmdGpu::ClampMode::Wrap);
            sampler.clamp_y.Assign(AmdGpu::ClampMode::Wrap);
            sampler.clamp_z.Assign(AmdGpu::ClampMode::Wrap);
        } else if (post_op == SharpFetchPostOp::ForceLastTexelXyClamp) {
            sampler.clamp_x.Assign(AmdGpu::ClampMode::ClampLastTexel);
            sampler.clamp_y.Assign(AmdGpu::ClampMode::ClampLastTexel);
            sampler.clamp_z.Assign(AmdGpu::ClampMode::Wrap);
        } else if (post_op == SharpFetchPostOp::ClearAnisoRatioAndThreshold) {
            sampler.max_aniso.Assign(AmdGpu::AnisoRatio::One);
            sampler.aniso_threshold.Assign(0);
        }
        return sampler;
    }
};
using SamplerResourceList = boost::container::static_vector<SamplerResource, NUM_SAMPLERS>;

struct FMaskResource {
    ImageResource source;

    constexpr AmdGpu::Image GetSharp(const auto& info) const noexcept {
        return source.GetSharp(info);
    }
};
using FMaskResourceList = boost::container::static_vector<FMaskResource, NUM_IMAGES>;

struct PushData {
    static constexpr u32 XOffsetIndex = 0;
    static constexpr u32 YOffsetIndex = 1;
    static constexpr u32 XScaleIndex = 2;
    static constexpr u32 YScaleIndex = 3;
    static constexpr u32 UdRegsIndex = 4;
    static constexpr u32 BufOffsetIndex = UdRegsIndex + NUM_USER_DATA_REGS / 4;
    static constexpr u32 MotionParamIndex = BufOffsetIndex + NUM_BUFFERS / 16 + 1;
    static constexpr u32 SceneSizeIndex = MotionParamIndex + 1;

    float xoffset;
    float yoffset;
    float xscale;
    float yscale;
    std::array<u32, NUM_USER_DATA_REGS> ud_regs;
    std::array<u8, NUM_BUFFERS> buf_offsets;
    u32 motion_param; ///< object motion parameter index (0: off)
    u32 scene_size; ///< reduced width | height << 16; zero means native pixel coordinates

    void AddOffset(u32 binding, u32 offset) {
        ASSERT(offset < 256 && binding < buf_offsets.size());
        buf_offsets[binding] = offset;
    }
};
static_assert(sizeof(PushData) <= 128,
              "PushData size is greater than minimum size guaranteed by Vulkan spec");

} // namespace Shader
