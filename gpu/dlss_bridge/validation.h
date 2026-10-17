#pragma once
#include "../shim/order1886_upscale.h"
#include <cmath>
#include <cstdio>

namespace order_dlss {
inline bool Fail(char* error, size_t size, const char* message) noexcept {
    if (error && size) std::snprintf(error, size, "%s", message);
    return false;
}
inline bool ValidateConfig(const OrderUpscaleConfig& c, char* error, size_t size) noexcept {
    constexpr uint32_t flags = ORDER_UPSCALE_HDR | ORDER_UPSCALE_DEPTH_INVERTED |
                               ORDER_UPSCALE_DEPTH_INFINITE | ORDER_UPSCALE_MOTION_JITTERED;
    if (!c.max_render_width || !c.max_render_height || !c.output_width || !c.output_height ||
        c.max_render_width > c.output_width || c.max_render_height > c.output_height ||
        c.output_width > 16384 || c.output_height > 16384 || (c.flags & ~flags))
        return Fail(error, size, "Invalid DLSS dimensions or unknown configuration flags");
    return true;
}
inline bool ValidateFrame(const OrderUpscaleFrame& f, const OrderUpscaleConfig& c,
                          char* error, size_t size) noexcept {
    if (!f.command_buffer || !f.render_width || !f.render_height ||
        f.render_width > c.max_render_width || f.render_height > c.max_render_height)
        return Fail(error, size, "Missing command buffer or render extent exceeds context");
    const OrderUpscaleImage* images[] = {&f.color, &f.depth, &f.motion, &f.output};
    const VkFormat formats[] = {VK_FORMAT_R16G16B16A16_SFLOAT, VK_FORMAT_R32_SFLOAT,
                                VK_FORMAT_R16G16_SFLOAT, VK_FORMAT_R16G16B16A16_SFLOAT};
    for (size_t n = 0; n < 4; ++n) {
        const auto& i = *images[n];
        if (!i.image || !i.view || i.format != formats[n])
            return Fail(error, size, "DLSS requires RGBA16F color/output, R32F depth, RG16F motion and valid views");
        if (n < 3) {
            if (i.width < f.render_width || i.height < f.render_height ||
                !(i.usage & VK_IMAGE_USAGE_SAMPLED_BIT) ||
                (i.layout != VK_IMAGE_LAYOUT_GENERAL && i.layout != VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL))
                return Fail(error, size, "DLSS inputs need sampled usage, sufficient extent and readable layout");
        } else if (i.width != c.output_width || i.height != c.output_height ||
                   (i.usage & (VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT)) !=
                       (VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT) ||
                   i.layout != VK_IMAGE_LAYOUT_GENERAL) {
            return Fail(error, size, "DLSS output needs configured extent, STORAGE|TRANSFER_DST usage and GENERAL layout");
        }
    }
    for (size_t n = 0; n < 3; ++n)
        if (images[n]->image == f.output.image)
            return Fail(error, size, "DLSS output must not alias an input image");
    if (!std::isfinite(f.jitter_x) || !std::isfinite(f.jitter_y) ||
        std::abs(f.jitter_x) > 1 || std::abs(f.jitter_y) > 1 ||
        !std::isfinite(f.motion_scale_x) || !std::isfinite(f.motion_scale_y) ||
        f.motion_scale_x == 0 || f.motion_scale_y == 0 ||
        !std::isfinite(f.frame_time_ms) || f.frame_time_ms <= 0 ||
        !std::isfinite(f.pre_exposure) || f.pre_exposure <= 0 ||
        !std::isfinite(f.camera_near) || f.camera_near <= 0 ||
        !std::isfinite(f.vertical_fov) || f.vertical_fov <= 0 || f.vertical_fov >= 3.14159265f ||
        f.reset_history > 1)
        return Fail(error, size, "Invalid DLSS jitter, motion scale, timing, exposure or camera metadata");
    if ((!(c.flags & ORDER_UPSCALE_DEPTH_INFINITE) && !std::isfinite(f.camera_far)) ||
        std::isnan(f.camera_far) || f.camera_far <= f.camera_near)
        return Fail(error, size, "Invalid DLSS far plane");
    return true;
}
}
