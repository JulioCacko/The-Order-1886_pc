#include <array>
#include <bit>
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <span>
#include <string_view>
#include <memory>
#include <vector>
#include <set>
#ifdef _WIN32
#include <process.h>
#else
#include <sys/wait.h>
#include <unistd.h>
#endif
#include "shader_recompiler/resource.h"
#include "shader_recompiler/ir/passes/fmask_identity.h"
// These imported headers predate this fixture's -Wextra/-Werror policy.
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-variable"
#pragma GCC diagnostic ignored "-Wunused-parameter"
#pragma GCC diagnostic ignored "-Wreorder"
#include "shader_recompiler/specialization.h"
#pragma GCC diagnostic pop
#include "video_core/renderer_vulkan/vk_image_binding_contract.h"
#include "video_core/renderer_vulkan/vk_permutation_info.h"
#include "shader_recompiler/ir/passes/srt_walker_cache.h"
#include "video_core/renderer_vulkan/vk_mapped_range_snapshot.h"

namespace Common::Log {
bool ShouldLog(Level) { return false; }
void Write(std::string_view, Level, const char*, int, const char*, std::string&&) {}
}
void assert_fail_impl() { std::_Exit(86); }
[[noreturn]] void unreachable_impl() { std::_Exit(86); }

static std::set<VAddr> mapped_image_bases{0x123400};
static u64 image_mapping_queries{};
namespace Core {
u64 MemoryManager::ClampRangeSize(VAddr address, u64 size) {
    ++image_mapping_queries;
    assert(size == 1); // Image eligibility checks only its base, not a full sparse range.
    return mapped_image_bases.contains(address) ? size : 0;
}
}

struct DescriptorInfo {
    // Backing storage exceeds the exposed span so the OOB fixture is safe even
    // against the old implementation; index 16 must still be rejected logically.
    std::array<u32, 64> storage{};
    size_t exposed = 8;
    u64 pgm_hash = 0x12345678;
    std::string_view hw_stage = "cpu-fixture";
    std::span<const u32> FlatUserData() const { return {storage.data(), exposed}; }
    u64 ProgramBase() const { return 0; }
    bool IsImageBaseMapped(VAddr address) const {
        auto* memory = Core::Memory::Instance();
        return memory->IsValidGpuMapping(address, 0) && memory->ClampRangeSize(address, 1) == 1;
    }
};

static AmdGpu::Image MakeImage() {
    auto image = AmdGpu::Image::Null(false);
    image.base_address = 0x1234;
    return image;
}

static Shader::ImageResource ImageBinding(DescriptorInfo& info) {
    Shader::ImageResource resource;
    const auto image = MakeImage();
    std::memcpy(info.storage.data(), &image, sizeof(image));
    std::memcpy(resource.sharp_fetch.immediates.data(), &image, sizeof(image));
    resource.sharp_fetch.load_mask = 0xff;
    for (u32 i = 0; i < 8; ++i) resource.sharp_fetch.offsets[i] = i;
    return resource;
}

static int ChildCase(std::string_view name) {
    DescriptorInfo info;
    if (name == "unknown-buffer" || name == "outside-buffer") {
        Shader::BufferResource buffer;
        buffer.sharp_fetch.load_mask = 1;
        buffer.sharp_fetch.offsets[0] = name == "unknown-buffer" ? Shader::UNKNOWN_LOCATION : 16;
        (void)buffer.GetSharp(info);
        return 0;
    }
    if (name == "unknown-sampler" || name == "outside-sampler" || name == "unknown-sampler-lod") {
        Shader::SamplerResource sampler;
        if (name == "unknown-sampler-lod") {
            sampler.post_op = Shader::SharpFetchPostOp::DisableAnisoIfSingleLod;
            sampler.post_op_tsharp_dw3_off = Shader::UNKNOWN_LOCATION;
        } else {
            sampler.sharp_fetch.load_mask = 1;
            sampler.sharp_fetch.offsets[0] = name == "unknown-sampler" ? Shader::UNKNOWN_LOCATION : 16;
        }
        (void)sampler.GetSharp(info);
        return 0;
    }
    auto resource = ImageBinding(info);
    if (name == "unknown-image") {
        resource.sharp_fetch.offsets[0] = Shader::UNKNOWN_LOCATION;
    } else if (name == "outside-image") {
        resource.sharp_fetch.offsets[0] = 16;
    } else {
        return 2;
    }
    (void)resource.GetSharp(info);
    return 0; // A missing source must not silently become a null/valid image.
}

static int SpawnCase(const char* executable, const char* name) {
#ifdef _WIN32
    const char* args[] = {executable, name, nullptr};
    return int(_spawnv(_P_WAIT, executable, args));
#else
    const auto child = fork();
    if (child == 0) {
        execl(executable, executable, name, nullptr);
        std::_Exit(127);
    }
    int status = 0;
    assert(waitpid(child, &status, 0) == child);
    return WIFEXITED(status) ? WEXITSTATUS(status) : -1;
#endif
}

static bool Check(bool passed, const char* name) {
    if (!passed) std::fprintf(stderr, "descriptor fixture failed: %s\n", name);
    return passed;
}

struct ForcedSrtHashCollision {
    size_t operator()(std::string_view) const noexcept { return 1; }
};

static bool CheckRuntimeCaches() {
    const std::array<u8, 4> walker_a{0x48, 0x8b, 0x07, 0xc3};
    const std::array<u8, 4> walker_a_copy{0x48, 0x8b, 0x07, 0xc3};
    const std::array<u8, 4> walker_b{0x48, 0x8b, 0x47, 0xc3};
    Shader::SrtWalkerCache<ForcedSrtHashCollision> walkers;
    if (!Check(walkers.Store(walker_a.data(), walker_a.size()), "SRT walker stored")) return false;
    if (!Check(walkers.Find(walker_a_copy.data(), walker_a_copy.size()) == walker_a.data(),
               "identical SRT walker reused")) return false;
    if (!Check(walkers.Find(walker_b.data(), walker_b.size()) == nullptr,
               "SRT hash collision requires byte equality")) return false;
    if (!Check(walkers.Store(walker_b.data(), walker_b.size()), "colliding SRT walker stored")) {
        return false;
    }
    if (!Check(walkers.Find(walker_b.data(), walker_b.size()) == walker_b.data(),
               "colliding SRT walker resolves to its own code")) return false;
    walkers.NotePatch();
    if (!Check(walkers.Find(walker_a_copy.data(), walker_a_copy.size()) == nullptr,
               "patched walker generation invalidates cached code")) return false;
    if (!Check(walkers.Store(walker_a_copy.data(), walker_a_copy.size()),
               "walker can be registered after patch invalidation")) return false;

    using Ranges = Vulkan::MappedRangeSnapshot::RangeSet;
    Vulkan::MappedRangeSnapshot snapshot;
    Ranges first;
    first += Ranges::interval_type::right_open(0x1000, 0x2000);
    if (!Check(!snapshot.IsCurrent(7, 0), "mapped cache begins unowned")) return false;
    snapshot.Refresh(7, 0, first);
    if (!Check(snapshot.Contains(0x1000, 16) && !snapshot.Contains(0x2000, 1),
               "mapped snapshot checks right-open ranges")) return false;

    Ranges second;
    second += Ranges::interval_type::right_open(0x3000, 0x4000);
    if (!Check(!snapshot.IsCurrent(7, 1), "map generation invalidates snapshot")) return false;
    snapshot.Refresh(7, 1, second);
    if (!Check(!snapshot.Contains(0x1000, 16) && snapshot.Contains(0x3000, 16),
               "refreshed snapshot sees map changes")) return false;
    if (!Check(!snapshot.IsCurrent(8, 1), "rasterizer identity invalidates snapshot")) return false;
    snapshot.Refresh(8, 1, first);
    if (!Check(snapshot.Contains(0x1000, 16) && !snapshot.Contains(0x3000, 16),
               "new rasterizer cannot inherit old ranges")) return false;
    return Check(!snapshot.Contains(std::numeric_limits<VAddr>::max() - 1, 4),
                 "overflowing mapped range is rejected");
}

static bool CheckImageLayerCounts() {
    const std::array<u32, 8> captured{0x104edf00, 0x00100000, 0x0063c3bf, 0x94e00204,
                                      0x000031b6, 0x00fff000, 0x05000000, 0x80000000};
    AmdGpu::Image image;
    std::memcpy(&image, captured.data(), sizeof(image));
    if (!Check(image.type == u64(AmdGpu::ImageType::Color2D) && image.width + 1 == 960 &&
                   image.height + 1 == 400 && image.depth == 4534 && image.NumLayers() == 1,
               "captured ordinary 2D ignores unused depth bits")) return false;

    for (const auto type : {AmdGpu::ImageType::Color1D, AmdGpu::ImageType::Color2D,
                            AmdGpu::ImageType::Color2DMsaa, AmdGpu::ImageType::Color3D}) {
        image.type = u64(type);
        image.depth = 8191;
        for (const u32 pow2pad : {0u, 1u}) {
            image.pow2pad = pow2pad;
            if (!Check(image.NumLayers() == 1 && image.depth == 8191,
                       "nonarray and volume images have one array layer")) return false;
        }
    }
    for (const auto type : {AmdGpu::ImageType::Color1DArray, AmdGpu::ImageType::Color2DArray,
                            AmdGpu::ImageType::Color2DMsaaArray}) {
        image.type = u64(type);
        image.depth = 4;
        image.pow2pad = 0;
        if (!Check(image.NumLayers() == 5, "array depth remains a layer count")) return false;
        image.pow2pad = 1;
        if (!Check(image.NumLayers() == 8, "array layer power-of-two padding")) return false;
        image.depth = 4534;
        image.pow2pad = 0;
        if (!Check(image.NumLayers() == 4535, "array layers are not device-limit clamped")) return false;
    }
    image.type = u64(AmdGpu::ImageType::Cube);
    for (const u32 depth : {0u, 1u, 2u}) {
        image.depth = depth;
        image.pow2pad = 0;
        if (!Check(image.NumLayers() == (depth + 1) * 6, "cube count expands to faces")) return false;
        image.pow2pad = 1;
        if (!Check(image.NumLayers() == std::bit_ceil((depth + 1) * 6),
                   "cube face power-of-two padding")) return false;
    }
    return true;
}

static bool CheckImageBindingContracts() {
    u32 next_binding = 7;
    const auto check = [&](bool storage, const AmdGpu::Image& sharp,
                           Shader::MipStorageFallbackMode mip_mode, u32 count,
                           u32 expected_binding, const char* name) {
        Shader::ImageResource declaration;
        declaration.is_written = storage;
        declaration.mip_fallback_mode = mip_mode;
        const auto contract = Vulkan::MakeImageBindingContract(declaration, sharp);
        vk::WriteDescriptorSet write;
        contract.Apply(write, next_binding);
        return Check(write.dstBinding == expected_binding && write.descriptorCount == count &&
                         write.descriptorType == (storage ? vk::DescriptorType::eStorageImage
                                                          : vk::DescriptorType::eSampledImage) &&
                         next_binding == expected_binding + count,
                     name);
    };
    const auto null = AmdGpu::Image::Null(false);
    using Mode = Shader::MipStorageFallbackMode;
    if (!check(false, null, Mode::None, 1, 7, "null sampled binding")) return false;
    if (!check(true, null, Mode::None, 1, 8, "null storage binding")) return false;
    // Binding metadata must survive rejection by the address/format guard. The helper
    // intentionally does not accept or reinterpret this guest address as an image.
    auto rejected = MakeImage();
    rejected.base_address = 0x1000000010ULL;
    if (!check(true, rejected, Mode::None, 1, 9, "rejected nonnull storage binding")) return false;
    auto array = null;
    array.base_level = 1;
    array.last_level = 3;
    if (!check(true, array, Mode::DynamicIndex, 3, 10, "null storage mip array")) return false;
    array.last_level = 2;
    if (!check(false, array, Mode::DynamicIndex, 2, 13, "subsequent sampled mip array")) return false;
    if (!check(false, null, Mode::None, 1, 15, "binding after mip arrays")) return false;
    return true;
}

static bool CheckPermutationMetadata() {
    struct SyntheticInfo {
        u64 pgm_base{};
        std::span<const u32> user_data;
        std::vector<u32> images;
        std::array<u32, 2> flattened{};
        u32 source_register{}, walker_bias{};
        void RefreshFlatBuf() {
            flattened = {user_data[source_register] + walker_bias, u32(images.size())};
        }
    };
    struct Module { std::unique_ptr<SyntheticInfo> info; };
    struct Params {
        u64 base;
        std::span<const u32> user_data;
        u64 Base() const { return base; }
    };
    std::vector<Module> modules;
    for (const u32 count : {36u, 35u}) {
        auto info = std::make_unique<SyntheticInfo>();
        info->images.resize(count);
        info->source_register = u32(modules.size());
        info->walker_bias = count * 100;
        modules.push_back({std::move(info)});
    }
    const auto* first_identity = modules[0].info.get();
    const auto* second_identity = modules[1].info.get();
    // Growing the module table cannot invalidate metadata held by existing pipelines.
    for (u32 i = 0; i < 64; ++i) modules.push_back({std::make_unique<SyntheticInfo>()});
    if (!Check(first_identity == modules[0].info.get() && second_identity == modules[1].info.get(),
               "stable permutation metadata ownership")) return false;
    const std::array<u32, 2> first_ud{11, 29}, second_ud{47, 83};
    auto& second = Vulkan::RefreshPermutationInfo(modules[1], Params{0x2000, first_ud});
    if (!Check(second.pgm_base == 0x2000 && second.flattened[0] == 3529 &&
                   second.images.size() == 35 && second.flattened[1] + 9 == 44,
               "new resource membership uses its own walker and sampler binding")) return false;
    const auto frozen = second;
    auto& first = Vulkan::RefreshPermutationInfo(modules[0], Params{0x3000, second_ud});
    if (!Check(first.flattened[0] == 3647 && first.flattened[1] + 9 == 45,
               "first permutation reselection")) return false;
    auto& reselected = Vulkan::RefreshPermutationInfo(modules[1], Params{0x4000, second_ud});
    if (!Check(reselected.flattened[0] == 3583 && frozen.flattened[0] == 3529 &&
                   reselected.images.size() == 35 && frozen.images.size() == 35,
               "cache hit refresh and immutable worker snapshot")) return false;
    return true;
}

static bool CheckSpecializationLayoutKeys() {
    Shader::Info info;
    Shader::StageSpecialization empty;
    empty.info = &info;
    auto shifted = empty;
    shifted.start.user_data = 2;
    info.ud_mask.mask = 1;
    if (!Check(!(empty == shifted) && !(shifted == empty),
               "resource-free shader must keep its user-data push-constant offset")) return false;
    info.ud_mask.mask = 0;
    if (!Check(empty == shifted && shifted == empty,
               "shader with no user-data reads may share resource-free permutations")) return false;
    Shader::StageSpecialization first;
    first.info = &info;
    first.images.emplace_back().num_bindings = 1;
    auto second = first;
    second.images[0].num_bindings = 3;
    if (!Check(!(first == second) && !(second == first),
               "null image array count participates in both key directions")) return false;
    second = first;
    second.images[0].is_fmask = true;
    if (!Check(!(first == second) && !(second == first),
               "normal to FMask classification participates in key")) return false;
    second = first;
    second.images.emplace_back().num_bindings = 1;
    if (!Check(!(first == second) && !(second == first),
               "resource membership participates in key")) return false;

    // A sample eliminated while the first translation saw FMask still reads its original
    // descriptor for key selection. Equal dimensions must not hide FMask -> normal changes.
    auto sharp = MakeImage();
    sharp.data_format = u64(AmdGpu::DataFormat::FormatFmask8_S2_F1);
    auto& dependency = info.fmasks.emplace_back();
    std::memcpy(dependency.source.sharp_fetch.immediates.data(), &sharp, sizeof(sharp));
    dependency.source.sharp_fetch.offsets.fill(Shader::UNKNOWN_LOCATION);
    const auto capture = [&] {
        Shader::StageSpecialization key;
        key.info = &info;
        u32 binding{};
        key.ForEachSharp(binding, key.fmasks, info.fmasks,
                         [](auto& spec, const auto&, AmdGpu::Image image) {
                             spec.width = image.width;
                             spec.height = image.height;
                         });
        return key;
    };
    const auto fmask = capture();
    sharp.data_format = u64(AmdGpu::DataFormat::Format8_8_8_8);
    sharp.num_format = u64(AmdGpu::NumberFormat::Uint);
    std::memcpy(dependency.source.sharp_fetch.immediates.data(), &sharp, sizeof(sharp));
    const auto normal = capture();
    if (!Check(fmask.fmasks[0].translation.is_fmask && !normal.fmasks[0].translation.is_fmask &&
                   !(fmask == normal) && !(normal == fmask),
               "eliminated FMask descriptor remains a classification dependency")) return false;
    sharp.num_format = u64(AmdGpu::NumberFormat::Float);
    std::memcpy(dependency.source.sharp_fetch.immediates.data(), &sharp, sizeof(sharp));
    const auto floating = capture();
    if (!Check(!(normal == floating) && !(floating == normal),
               "first FMask then normal UINT to FLOAT remains keyed")) return false;
    dependency.source.mip_fallback_mode = Shader::MipStorageFallbackMode::DynamicIndex;
    sharp.last_level = 2;
    std::memcpy(dependency.source.sharp_fetch.immediates.data(), &sharp, sizeof(sharp));
    const auto mip_array = capture();
    sharp.last_level = 4;
    std::memcpy(dependency.source.sharp_fetch.immediates.data(), &sharp, sizeof(sharp));
    const auto larger_array = capture();
    if (!Check(!(mip_array == larger_array) && !(larger_array == mip_array),
               "first FMask then normal binding count remains keyed")) return false;
    return true;
}

static bool CheckFmaskIdentityComponents() {
    using C = AmdGpu::CompSwizzle;
    const auto replicated = Shader::Optimization::FmaskIdentityTexel(
        {.array = std::array{C::Red,C::Red,C::Red,C::Red}});
    if (!Check(replicated && *replicated == std::array<u32,4>{0x76543210,0x76543210,
                                                            0x76543210,0x76543210},
               "FMask Z selecting X has the low identity payload")) return false;
    const auto selected = Shader::Optimization::FmaskIdentityTexel(
        {.array = std::array{C::Green,C::Red,C::Zero,C::One}});
    if (!Check(selected && *selected == std::array<u32,4>{0xfedcba98,0x76543210,0,1},
               "FMask explicit R G zero one selectors")) return false;
    if (!Check(!Shader::Optimization::FmaskIdentityTexel(
                   {.array = std::array{C::Red,C::Blue,C::Red,C::Red}}) &&
                   !Shader::Optimization::FmaskIdentityTexel(
                   {.array = std::array{C::Red,C::Red,C::Alpha,C::Red}}),
               "unestablished FMask payload channels remain unsupported")) return false;
    return true;
}

static bool CheckUnmappedImagePolicy() {
    // Exact malformed descriptor captured in srt-failure-context-1: address 0x1000,
    // FMask-looking format46/number1 and reserved selector3. It is not a real FMask.
    const std::array<u32,8> captured{0x00000010,0x86e575c0,0x00000010,0x86e57590,
                                    0x00000010,0x0224ce40,0x00000000,0x00008008};
    DescriptorInfo data;
    auto resource = ImageBinding(data);
    std::memcpy(data.storage.data(), captured.data(), sizeof(captured));
    const auto original_fetch = resource.sharp_fetch;
    const auto null = resource.GetSharp(data);
    AmdGpu::Image original;
    assert(resource.Fetch(data.storage.data(), &original));
    if (!Check(original.Address() == 0x1000 && null.Address() == 0 &&
                   !AmdGpu::IsFmask(null.GetDataFmt()) && resource.sharp_fetch == original_fetch &&
                   std::memcmp(data.storage.data(), captured.data(), sizeof(captured)) == 0,
               "unmapped malformed T# becomes local null before FMask classification")) return false;

    auto valid = MakeImage();
    valid.base_address = 0x10;
    valid.data_format = u64(AmdGpu::DataFormat::FormatFmask8_S2_F1);
    valid.num_format = u64(AmdGpu::NumberFormat::Uint);
    valid.dst_sel_x = valid.dst_sel_y = valid.dst_sel_z = valid.dst_sel_w =
        u64(AmdGpu::CompSwizzle::Red);
    Shader::Info info;
    info.flattened_ud_buf.resize(8);
    std::memcpy(info.flattened_ud_buf.data(), &valid, sizeof(valid));
    info.images.push_back(resource);
    const auto key = [&] {
        Shader::StageSpecialization result;
        result.info = &info;
        u32 binding{};
        result.ForEachSharp(binding, result.images, info.images,
                            [](auto& spec, const auto& desc, AmdGpu::Image sharp) {
                                spec = Shader::StageSpecialization::DescribeImage(desc, sharp);
                            });
        return result;
    };
    const auto unmapped = key();
    mapped_image_bases.insert(0x1000);
    const auto mapped = key();
    const auto retried = info.images[0].GetSharp(info);
    if (!Check(retried.Address() == 0x1000 && AmdGpu::IsFmask(retried.GetDataFmt()) &&
                   !(unmapped == mapped) && !(mapped == unmapped),
               "later mapped descriptor is retried and changes specialization")) return false;
    mapped_image_bases.erase(0x1000);

    // A previously compiled three-binding layout remains three bindings during cache
    // warmup, even with no VMAs. Live specialization still sees current descriptor shape.
    auto& array = info.images[0];
    array.is_written = true;
    array.mip_fallback_mode = Shader::MipStorageFallbackMode::DynamicIndex;
    array.declared_binding_count = 3;
    valid.data_format = u64(AmdGpu::DataFormat::Format8_8_8_8);
    valid.num_format = u64(AmdGpu::NumberFormat::Unorm);
    valid.base_level = 1; valid.last_level = 3;
    std::memcpy(info.flattened_ud_buf.data(), &valid, sizeof(valid));
    const auto before_layout = image_mapping_queries;
    if (!Check(array.NumBindings(info) == 3 && image_mapping_queries == before_layout,
               "cache warm layout uses immutable count without guest mapping")) return false;
    auto contract = Vulkan::MakeImageBindingContract(array, array.GetSharp(info));
    if (!Check(contract.storage && contract.count == 3,
               "early-null storage binding retains declared array count")) return false;
    const auto no_vma = key();
    mapped_image_bases.insert(0x1000);
    const auto with_vma = key();
    if (!Check(no_vma.images[0].num_bindings == 1 && with_vma.images[0].num_bindings == 3 &&
                   !(no_vma == with_vma) && !(with_vma == no_vma),
               "live specialization uses current count instead of frozen layout count")) return false;
    mapped_image_bases.erase(0x1000);
    return true;
}

int main(int argc, char** argv) {
    if (argc > 1) return ChildCase(argv[1]);
    if (!CheckRuntimeCaches()) return 1;
    if (!CheckImageLayerCounts()) return 1;
    if (!CheckImageBindingContracts()) return 1;
    if (!CheckPermutationMetadata()) return 1;
    if (!CheckSpecializationLayoutKeys()) return 1;
    if (!CheckFmaskIdentityComponents()) return 1;
    if (!CheckUnmappedImagePolicy()) return 1;
    DescriptorInfo info;
    auto resource = ImageBinding(info);
    // Register zero is a valid source; it must not be confused with an absent
    // non-userdata flat offset (which uses the explicit UNKNOWN_LOCATION tag).
    if (!Check(resource.GetSharp(info).base_address == MakeImage().base_address,
               "SGPR0 source")) return 1;
    // A declared packed format must remain unchanged. Vulkan conversion support
    // is a separate requirement; this source validator must not invent a fallback.
    auto packed = MakeImage();
    packed.data_format = u64(AmdGpu::DataFormat::FormatBG_RG);
    packed.num_format = u64(AmdGpu::NumberFormat::Srgb);
    std::memcpy(info.storage.data(), &packed, sizeof(packed));
    const auto fetched = resource.GetSharp(info);
    if (!Check(fetched.data_format == packed.data_format && fetched.num_format == packed.num_format,
               "declared BG_RG/Srgb is not remapped")) return 1;
    resource.sharp_fetch.load_mask = 0;
    resource.sharp_fetch.offsets.fill(Shader::UNKNOWN_LOCATION);
    // Synthetic immediates do not read their unused location entries.
    if (!Check(resource.GetSharp(info).base_address == MakeImage().base_address,
               "synthetic immediate ignores unused location")) return 1;
    resource = ImageBinding(info);
    resource.is_r128 = true;
    for (u32 i = 4; i < 8; ++i) resource.sharp_fetch.offsets[i] = Shader::UNKNOWN_LOCATION;
    auto r128 = MakeImage();
    if (!Check(resource.Fetch(info.FlatUserData().data(), &r128), "R128 four-dword fetch")) return 1;
    for (const char* name : {"unknown-image", "outside-image", "unknown-buffer", "outside-buffer",
                             "unknown-sampler", "outside-sampler", "unknown-sampler-lod"}) {
        const int result = SpawnCase(argv[0], name);
        if (result != 86) {
            std::fprintf(stderr, "%s: expected descriptor assertion 86, got %d\n", name, result);
            return 1;
        }
    }
}
