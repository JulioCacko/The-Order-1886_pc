#include "validation.h"
#include <cstdlib>
#include <iostream>
#include <limits>

static void Check(bool condition, const char* message) {
    if (!condition) { std::cerr << message << '\n'; std::exit(1); }
}

int main() {
    OrderUpscaleConfig config{1920, 1080, 3840, 2160, ORDER_UPSCALE_HDR};
    OrderUpscaleFrame frame{};
    frame.command_buffer = reinterpret_cast<VkCommandBuffer>(1);
    auto image = [](uintptr_t id, VkFormat format, VkImageUsageFlags usage, uint32_t w, uint32_t h) {
        return OrderUpscaleImage{reinterpret_cast<VkImage>(id), reinterpret_cast<VkImageView>(id),
                                 format, w, h, usage, VK_IMAGE_LAYOUT_GENERAL};
    };
    frame.color = image(1, VK_FORMAT_R16G16B16A16_SFLOAT, VK_IMAGE_USAGE_SAMPLED_BIT, 1920, 1080);
    frame.depth = image(2, VK_FORMAT_R32_SFLOAT, VK_IMAGE_USAGE_SAMPLED_BIT, 1920, 1080);
    frame.motion = image(3, VK_FORMAT_R16G16_SFLOAT, VK_IMAGE_USAGE_SAMPLED_BIT, 1920, 1080);
    frame.output = image(4, VK_FORMAT_R16G16B16A16_SFLOAT,
        VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT, 3840, 2160);
    frame.render_width = 1920; frame.render_height = 1080;
    frame.motion_scale_x = frame.motion_scale_y = frame.pre_exposure = 1;
    frame.frame_time_ms = 16.67f; frame.camera_near = 0.1f;
    frame.camera_far = 1000; frame.vertical_fov = 1;
    char error[128]{};
    Check(order_dlss::ValidateConfig(config, error, sizeof(error)), "valid config rejected");
    Check(order_dlss::ValidateFrame(frame, config, error, sizeof(error)), "valid frame rejected");
    auto reject = [&](OrderUpscaleFrame bad) {
        error[0] = 0;
        Check(!order_dlss::ValidateFrame(bad, config, error, sizeof(error)), "invalid frame accepted");
        Check(error[0] != 0, "missing actionable error");
    };
    auto bad = frame; bad.command_buffer = VK_NULL_HANDLE; reject(bad);
    bad = frame; bad.render_width = 0; reject(bad);
    bad = frame; bad.render_width = 1921; reject(bad);
    bad = frame; bad.depth.image = VK_NULL_HANDLE; reject(bad);
    bad = frame; bad.motion.view = VK_NULL_HANDLE; reject(bad);
    bad = frame; bad.color.format = VK_FORMAT_R8G8B8A8_UNORM; reject(bad);
    bad = frame; bad.depth.format = VK_FORMAT_D32_SFLOAT; reject(bad);
    bad = frame; bad.motion.format = VK_FORMAT_R32G32_SFLOAT; reject(bad);
    bad = frame; bad.output.width = 1920; reject(bad);
    bad = frame; bad.color.width = 1919; reject(bad);
    bad = frame; bad.color.usage = VK_IMAGE_USAGE_STORAGE_BIT; reject(bad);
    bad = frame; bad.output.usage = VK_IMAGE_USAGE_SAMPLED_BIT; reject(bad);
    bad = frame; bad.output.usage = VK_IMAGE_USAGE_STORAGE_BIT; reject(bad);
    bad = frame; bad.output.image = bad.color.image; reject(bad);
    bad = frame; bad.depth.layout = VK_IMAGE_LAYOUT_UNDEFINED; reject(bad);
    bad = frame; bad.output.layout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL; reject(bad);
    bad = frame; bad.jitter_x = std::numeric_limits<float>::quiet_NaN(); reject(bad);
    bad = frame; bad.pre_exposure = 0; reject(bad);
    bad = frame; bad.frame_time_ms = -1; reject(bad);
    bad = frame; bad.motion_scale_x = 0; reject(bad);
    bad = frame; bad.camera_far = bad.camera_near; reject(bad);
    bad = frame; bad.vertical_fov = 4; reject(bad);
    bad = frame; bad.reset_history = 2; reject(bad);
    auto invalid = config; invalid.max_render_width = 0;
    Check(!order_dlss::ValidateConfig(invalid, error, sizeof(error)), "zero config accepted");
    invalid = config; invalid.flags |= 0x80000000u;
    Check(!order_dlss::ValidateConfig(invalid, error, sizeof(error)), "unknown flags accepted");
    std::cout << "DLSS CPU contracts passed (23 invalid frames, 2 invalid configs)\n";
}
