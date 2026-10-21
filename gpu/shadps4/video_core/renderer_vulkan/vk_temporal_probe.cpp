// SPDX-License-Identifier: GPL-2.0-or-later
// Temporal input probe (#7). See vk_temporal_probe.h and host_shaders/temporal_probe.comp.

#include <array>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <optional>

#include "video_core/host_shaders/temporal_probe_comp.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_rasterizer.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/renderer_vulkan/vk_shader_util.h"
#include "video_core/renderer_vulkan/vk_temporal_probe.h"
#include "video_core/texture_cache/texture_cache.h"

#include <vk_mem_alloc.h>

namespace Vulkan {

namespace {

struct Sums {
    u32 error[3];
    u32 pixels, saturated, moving;
};

struct Constants {
    u32 width, height;
    float scale;
    u32 samples;
    u32 has_previous;
};

/// Pixels per velocity unit: constant 63 of the game's resolve (docs/order1886-frame-map.md).
constexpr float VelocityScale = 16.0f;
/// Frames per logged line.
constexpr u32 ReportEvery = 120;

struct Probe {
    vk::Device device;
    VmaAllocator allocator{};
    vk::UniqueSampler sampler;
    vk::UniqueDescriptorSetLayout set_layout;
    vk::UniquePipelineLayout layout;
    vk::UniquePipeline pipeline;
    // Ping-pong resolved color: one is written this frame, the other holds the previous frame.
    std::array<std::optional<VideoCore::UniqueImage>, 2> resolved;
    std::array<vk::UniqueImageView, 2> views;
    std::array<vk::ImageLayout, 2> layouts{};
    u32 width = 0, height = 0, current = 0;
    bool has_previous = false;
    bool reported_inputs = false;
    // Totals since the last report, filled by the readbacks.
    std::atomic<u64> error[3]{}, pixels{}, saturated{}, moving{}, frames{};

    void Create(const Instance& instance) {
        device = instance.GetDevice();
        allocator = instance.GetAllocator();
        sampler = Check(device.createSamplerUnique(vk::SamplerCreateInfo{
            .magFilter = vk::Filter::eLinear,
            .minFilter = vk::Filter::eLinear,
            .mipmapMode = vk::SamplerMipmapMode::eNearest,
            .addressModeU = vk::SamplerAddressMode::eClampToEdge,
            .addressModeV = vk::SamplerAddressMode::eClampToEdge,
            .addressModeW = vk::SamplerAddressMode::eClampToEdge,
            .maxLod = 0.0f,
        }));
        const std::array<vk::DescriptorSetLayoutBinding, 5> bindings{{
            {0, vk::DescriptorType::eSampledImage, 1, vk::ShaderStageFlagBits::eCompute},
            {1, vk::DescriptorType::eSampledImage, 1, vk::ShaderStageFlagBits::eCompute},
            {2, vk::DescriptorType::eCombinedImageSampler, 1, vk::ShaderStageFlagBits::eCompute,
             &sampler.get()},
            {3, vk::DescriptorType::eStorageImage, 1, vk::ShaderStageFlagBits::eCompute},
            {4, vk::DescriptorType::eStorageBuffer, 1, vk::ShaderStageFlagBits::eCompute},
        }};
        set_layout = Check(device.createDescriptorSetLayoutUnique({
            .flags = vk::DescriptorSetLayoutCreateFlagBits::ePushDescriptorKHR,
            .bindingCount = static_cast<u32>(bindings.size()),
            .pBindings = bindings.data(),
        }));
        const vk::PushConstantRange range{vk::ShaderStageFlagBits::eCompute, 0, sizeof(Constants)};
        layout = Check(device.createPipelineLayoutUnique({
            .setLayoutCount = 1,
            .pSetLayouts = &*set_layout,
            .pushConstantRangeCount = 1,
            .pPushConstantRanges = &range,
        }));
        const auto module = CompileSPV(TEMPORAL_PROBE_COMP, device);
        pipeline = Check(device.createComputePipelineUnique(
            {}, vk::ComputePipelineCreateInfo{
                    .stage = {.stage = vk::ShaderStageFlagBits::eCompute,
                              .module = module,
                              .pName = "main"},
                    .layout = *layout,
                }));
        device.destroyShaderModule(module);
    }

    void Resize(u32 w, u32 h) {
        width = w;
        height = h;
        has_previous = false;
        for (u32 i = 0; i < 2; ++i) {
            views[i].reset();
            resolved[i].emplace(device, allocator);
            resolved[i]->Create(vk::ImageCreateInfo{
                .imageType = vk::ImageType::e2D,
                .format = vk::Format::eR16G16B16A16Sfloat,
                .extent = {w, h, 1},
                .mipLevels = 1,
                .arrayLayers = 1,
                .samples = vk::SampleCountFlagBits::e1,
                .usage = vk::ImageUsageFlagBits::eSampled | vk::ImageUsageFlagBits::eStorage,
                .initialLayout = vk::ImageLayout::eUndefined,
            });
            views[i] = Check(device.createImageViewUnique({
                .image = *resolved[i],
                .viewType = vk::ImageViewType::e2D,
                .format = vk::Format::eR16G16B16A16Sfloat,
                .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
            }));
            layouts[i] = vk::ImageLayout::eUndefined;
        }
    }

    void Report() {
        const u64 compared = pixels.exchange(0);
        const u64 n = frames.exchange(0);
        const double scale = compared ? 1.0 / (4096.0 * double(compared)) : 0.0;
        const double none = double(error[0].exchange(0)) * scale;
        const double plus = double(error[1].exchange(0)) * scale;
        const double minus = double(error[2].exchange(0)) * scale;
        const u64 sat = saturated.exchange(0), mov = moving.exchange(0);
        const char* best = !compared                       ? "no moving pixels"
                           : plus < minus && plus < none   ? "+velocity"
                           : minus < plus && minus < none  ? "-velocity"
                                                           : "no motion";
        std::printf("Temporal probe: %llu frames, %llu compared pixels (%llu moving, %llu "
                    "saturated); mean |dLuma| no motion %.5f, +velocity %.5f, -velocity %.5f; "
                    "best %s\n",
                    static_cast<unsigned long long>(n), static_cast<unsigned long long>(compared),
                    static_cast<unsigned long long>(mov), static_cast<unsigned long long>(sat),
                    none, plus, minus, best);
        std::fflush(stdout);
    }
};

Probe& State() {
    static Probe probe;
    return probe;
}

} // namespace

bool TemporalProbeEnabled() {
    static const bool enabled = [] {
        const char* env = std::getenv("ORDER1886_TEMPORAL_PROBE");
        return env && *env == '1';
    }();
    return enabled;
}

void RunTemporalProbe(Rasterizer& rasterizer, std::span<const VideoCore::ImageId> images) {
    auto& runtime = rasterizer.GetRuntime();
    auto& texture_cache = rasterizer.GetTextureCache();
    auto& scheduler = runtime.GetScheduler();
    const auto& instance = runtime.GetInstance();
    auto& probe = State();
    if (!probe.pipeline) {
        probe.Create(instance);
    }

    VideoCore::Image* color = nullptr;
    VideoCore::Image* velocity = nullptr;
    for (const auto id : images) {
        auto& image = texture_cache.GetImage(id);
        if (image.info.num_samples > 1) {
            color = &image;
        } else if (image.info.pixel_format == vk::Format::eA2B10G10R10UnormPack32) {
            velocity = &image;
        }
    }
    if (!color || !velocity || velocity->info.size.width != color->info.size.width ||
        velocity->info.size.height != color->info.size.height) {
        if (!probe.reported_inputs) {
            probe.reported_inputs = true;
            std::printf("Temporal probe: resolve inputs not identified (%zu images bound)\n",
                        images.size());
        }
        return;
    }
    const u32 w = color->info.size.width, h = color->info.size.height;
    if (!probe.reported_inputs) {
        probe.reported_inputs = true;
        std::printf("Temporal probe: scene color %ux%u %s x%u, velocity %ux%u %s, scale %.0f px\n",
                    w, h, vk::to_string(color->info.pixel_format).c_str(),
                    color->info.num_samples, velocity->info.size.width,
                    velocity->info.size.height,
                    vk::to_string(velocity->info.pixel_format).c_str(), VelocityScale);
    }
    if (w != probe.width || h != probe.height) {
        probe.Resize(w, h);
    }

    VideoCore::ImageViewInfo color_info{};
    color_info.format = color->info.pixel_format;
    VideoCore::ImageViewInfo velocity_info{};
    velocity_info.format = velocity->info.pixel_format;
    const vk::ImageView color_view = *color->FindView(color_info).image_view;
    const vk::ImageView velocity_view = *velocity->FindView(velocity_info).image_view;
    runtime.Transit(color, vk::ImageLayout::eShaderReadOnlyOptimal,
                    vk::PipelineStageFlagBits2::eComputeShader, vk::AccessFlagBits2::eShaderRead);
    runtime.Transit(velocity, vk::ImageLayout::eShaderReadOnlyOptimal,
                    vk::PipelineStageFlagBits2::eComputeShader, vk::AccessFlagBits2::eShaderRead);
    runtime.FlushBarriers();

    // The sums go to a small host-visible buffer read back once the GPU has finished.
    const VkBufferCreateInfo buffer_ci{.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
                                       .size = sizeof(Sums),
                                       .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT};
    const VmaAllocationCreateInfo alloc_ci{
        .flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT,
        .usage = VMA_MEMORY_USAGE_AUTO_PREFER_HOST};
    VkBuffer buffer{};
    VmaAllocation allocation{};
    VmaAllocationInfo info{};
    if (vmaCreateBuffer(probe.allocator, &buffer_ci, &alloc_ci, &buffer, &allocation, &info) !=
        VK_SUCCESS) {
        return;
    }
    std::memset(info.pMappedData, 0, sizeof(Sums));
    vmaFlushAllocation(probe.allocator, allocation, 0, VK_WHOLE_SIZE);

    const u32 write = probe.current, read = probe.current ^ 1;
    const Constants constants{w, h, VelocityScale, color->info.num_samples,
                              probe.has_previous ? 1u : 0u};
    const vk::ImageLayout write_from = probe.layouts[write], read_from = probe.layouts[read];
    const vk::Image write_image = *probe.resolved[write], read_image = *probe.resolved[read];
    const vk::ImageView write_view = *probe.views[write], read_view = *probe.views[read];
    const bool has_previous = probe.has_previous;
    scheduler.EndRendering();
    scheduler.Record([=, &probe](vk::CommandBuffer cmdbuf) {
        std::array<vk::ImageMemoryBarrier2, 2> barriers{{
            {.srcStageMask = vk::PipelineStageFlagBits2::eComputeShader,
             .srcAccessMask = vk::AccessFlagBits2::eShaderRead,
             .dstStageMask = vk::PipelineStageFlagBits2::eComputeShader,
             .dstAccessMask = vk::AccessFlagBits2::eShaderWrite,
             .oldLayout = write_from,
             .newLayout = vk::ImageLayout::eGeneral,
             .image = write_image,
             .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1}},
            {.srcStageMask = vk::PipelineStageFlagBits2::eComputeShader,
             .srcAccessMask = vk::AccessFlagBits2::eShaderWrite,
             .dstStageMask = vk::PipelineStageFlagBits2::eComputeShader,
             .dstAccessMask = vk::AccessFlagBits2::eShaderRead,
             .oldLayout = read_from,
             .newLayout = vk::ImageLayout::eShaderReadOnlyOptimal,
             .image = read_image,
             .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1}},
        }};
        cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = has_previous ? 2u : 1u,
                                 .pImageMemoryBarriers = barriers.data()});
        const vk::DescriptorImageInfo color_desc{{}, color_view, vk::ImageLayout::eShaderReadOnlyOptimal};
        const vk::DescriptorImageInfo velocity_desc{{}, velocity_view,
                                                    vk::ImageLayout::eShaderReadOnlyOptimal};
        // Without a previous frame the shader returns before sampling it; bind the written image
        // in General layout so the descriptor stays valid.
        const vk::DescriptorImageInfo previous_desc{
            {}, has_previous ? read_view : write_view,
            has_previous ? vk::ImageLayout::eShaderReadOnlyOptimal : vk::ImageLayout::eGeneral};
        const vk::DescriptorImageInfo resolved_desc{{}, write_view, vk::ImageLayout::eGeneral};
        const vk::DescriptorBufferInfo sums_desc{buffer, 0, sizeof(Sums)};
        const std::array<vk::WriteDescriptorSet, 5> writes{{
            {.dstBinding = 0, .descriptorCount = 1, .descriptorType = vk::DescriptorType::eSampledImage, .pImageInfo = &color_desc},
            {.dstBinding = 1, .descriptorCount = 1, .descriptorType = vk::DescriptorType::eSampledImage, .pImageInfo = &velocity_desc},
            {.dstBinding = 2, .descriptorCount = 1, .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &previous_desc},
            {.dstBinding = 3, .descriptorCount = 1, .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &resolved_desc},
            {.dstBinding = 4, .descriptorCount = 1, .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &sums_desc},
        }};
        cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, *probe.pipeline);
        cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, *probe.layout, 0, writes);
        cmdbuf.pushConstants(*probe.layout, vk::ShaderStageFlagBits::eCompute, 0,
                             sizeof(constants), &constants);
        cmdbuf.dispatch((w + 7) / 8, (h + 7) / 8, 1);
    });
    probe.layouts[write] = vk::ImageLayout::eGeneral;
    if (has_previous) {
        probe.layouts[read] = vk::ImageLayout::eShaderReadOnlyOptimal;
    }
    probe.current = read;
    probe.has_previous = true;

    scheduler.DeferPriorityOperation([&probe, allocator = probe.allocator, buffer, allocation,
                                      mapped = info.pMappedData, measured = has_previous] {
        vmaInvalidateAllocation(allocator, allocation, 0, VK_WHOLE_SIZE);
        Sums sums;
        std::memcpy(&sums, mapped, sizeof(sums));
        vmaDestroyBuffer(allocator, buffer, allocation);
        if (!measured) {
            return;
        }
        for (u32 i = 0; i < 3; ++i) {
            probe.error[i] += sums.error[i];
        }
        probe.pixels += sums.pixels;
        probe.saturated += sums.saturated;
        probe.moving += sums.moving;
        if (++probe.frames >= ReportEvery) {
            probe.Report();
        }
    });
}

} // namespace Vulkan
