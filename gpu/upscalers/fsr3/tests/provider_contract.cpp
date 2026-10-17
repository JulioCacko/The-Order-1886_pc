#include "order1886_upscale.h"
#include "ffx_vk_portable.h"
#include <cmath>
#include <cstdio>
#include <cstring>
#include <limits>
#include <stdexcept>

extern "C" OrderUpscaleStatus order1886_fsr_get_api(uint32_t, OrderUpscaleProviderApi*);

// The SDK boundary allocates GPU images/pipelines and records Vulkan commands.
// Keep CPU checks on the real provider while replacing those external effects.
static FfxVkPortableDeviceInfo seen_device{};
static FfxVkPortableUpscaleCreateInfo seen_config{};
static FfxVkPortableUpscaleDispatchInfo seen_frame{};
static FfxVkPortableResult create_result = FFX_VK_PORTABLE_OK;
static FfxVkPortableResult dispatch_result = FFX_VK_PORTABLE_OK;
static bool throw_create = false, throw_dispatch = false;
static bool null_create = false, partial_create = false, throw_destroy = false;
static int creates = 0, dispatches = 0, destroys = 0, failures = 0;
static VkQueueFlags queue_flags = VK_QUEUE_GRAPHICS_BIT | VK_QUEUE_COMPUTE_BIT;
static uint32_t api_version = VK_API_VERSION_1_2;
static uintptr_t backend_storage;

#define CHECK(value) do { if (!(value)) { std::fprintf(stderr, "line %d: %s\n", __LINE__, #value); ++failures; } } while (0)
template <class T> static T handle(uintptr_t n) { return (T)n; }

extern "C" FfxVkPortableResult ffxVkPortableUpscaleContextCreate(
    const FfxVkPortableDeviceInfo* device, const FfxVkPortableUpscaleCreateInfo* config,
    FfxVkPortableUpscaleContext** context) {
    ++creates;
    if (throw_create) throw std::runtime_error("create failure");
    seen_device = *device;
    seen_config = *config;
    *context = !null_create && (create_result == FFX_VK_PORTABLE_OK || partial_create)
        ? reinterpret_cast<FfxVkPortableUpscaleContext*>(&backend_storage) : nullptr;
    return create_result;
}
extern "C" FfxVkPortableResult ffxVkPortableUpscaleContextRecordDispatch(
    FfxVkPortableUpscaleContext*, const FfxVkPortableUpscaleDispatchInfo* frame) {
    ++dispatches;
    seen_frame = *frame;
    if (throw_dispatch) throw std::runtime_error("dispatch failure");
    return dispatch_result;
}
extern "C" FfxVkPortableResult ffxVkPortableUpscaleContextDestroy(FfxVkPortableUpscaleContext*) {
    ++destroys;
    if (throw_destroy) throw std::runtime_error("destroy failure");
    return FFX_VK_PORTABLE_OK;
}
static void VKAPI_CALL properties(VkPhysicalDevice, VkPhysicalDeviceProperties* out) {
    *out = {};
    out->apiVersion = api_version;
    out->limits.maxImageDimension2D = 16384;
}
static void VKAPI_CALL queues(VkPhysicalDevice, uint32_t* count, VkQueueFamilyProperties* out) {
    if (out && *count) { *out = {}; out->queueFlags = queue_flags; out->queueCount = 1; }
    *count = 1;
}
static PFN_vkVoidFunction VKAPI_CALL instance_proc(VkInstance, const char* name) {
    if (!std::strcmp(name, "vkGetPhysicalDeviceProperties")) return reinterpret_cast<PFN_vkVoidFunction>(properties);
    if (!std::strcmp(name, "vkGetPhysicalDeviceQueueFamilyProperties")) return reinterpret_cast<PFN_vkVoidFunction>(queues);
    return nullptr;
}
static PFN_vkVoidFunction VKAPI_CALL device_proc(VkDevice, const char*) { return nullptr; }
static OrderUpscaleDevice device() {
    OrderUpscaleDevice d{};
    d.instance = handle<VkInstance>(1); d.physical_device = handle<VkPhysicalDevice>(2);
    d.device = handle<VkDevice>(3); d.graphics_queue = handle<VkQueue>(4);
    d.get_instance_proc_addr = instance_proc; d.get_device_proc_addr = device_proc;
    d.shader_storage_image_write_without_format_enabled = VK_TRUE;
    return d;
}
static OrderUpscaleConfig config() { return {1920, 1080, 3840, 2160, ORDER_UPSCALE_HDR}; }
static OrderUpscaleImage image(uintptr_t n, VkFormat format, uint32_t w, uint32_t h, bool output = false) {
    return {handle<VkImage>(n), handle<VkImageView>(n + 10), format, w, h,
            output ? VK_IMAGE_USAGE_STORAGE_BIT : VK_IMAGE_USAGE_SAMPLED_BIT,
            output ? VK_IMAGE_LAYOUT_GENERAL : VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL};
}
static OrderUpscaleFrame frame() {
    OrderUpscaleFrame f{};
    f.command_buffer = handle<VkCommandBuffer>(5);
    f.color = image(20, VK_FORMAT_R16G16B16A16_SFLOAT, 1920, 1080);
    f.depth = image(21, VK_FORMAT_R32_SFLOAT, 1920, 1080);
    f.motion = image(22, VK_FORMAT_R16G16_SFLOAT, 1920, 1080);
    f.output = image(23, VK_FORMAT_R16G16B16A16_SFLOAT, 3840, 2160, true);
    f.render_width = 1920; f.render_height = 1080;
    f.jitter_x = -0.125f; f.jitter_y = 0.25f;
    f.motion_scale_x = 1920; f.motion_scale_y = -1080;
    f.frame_time_ms = 16.5f; f.pre_exposure = 1.25f;
    f.camera_near = 0.1f; f.camera_far = 1000; f.vertical_fov = 1.1f;
    return f;
}
int main() {
    OrderUpscaleProviderApi api{};
    CHECK(order1886_fsr_get_api(ORDER1886_UPSCALE_ABI + 1, &api) == ORDER_UPSCALE_UNSUPPORTED);
    CHECK(order1886_fsr_get_api(ORDER1886_UPSCALE_ABI, nullptr) == ORDER_UPSCALE_INVALID_ARGUMENT);
    if (order1886_fsr_get_api(ORDER1886_UPSCALE_ABI, &api) != ORDER_UPSCALE_OK) {
        std::fprintf(stderr, "FSR provider ABI is unavailable\n"); return 1;
    }
    CHECK(api.abi_version == ORDER1886_UPSCALE_ABI);
    CHECK(api.name && api.version && api.create && api.dispatch && api.destroy);
    char error[128]{};
    uint32_t count = 99; const char* const* names = reinterpret_cast<const char* const*>(uintptr_t{1});
    CHECK(api.required_instance_extensions(&count, &names, error, sizeof(error)) == ORDER_UPSCALE_OK);
    CHECK(count == 0 && names == nullptr && error[0] == '\0');
    CHECK(api.required_instance_extensions(nullptr, &names, error, sizeof(error)) == ORDER_UPSCALE_INVALID_ARGUMENT);
    CHECK(api.required_instance_extensions(&count, nullptr, error, sizeof(error)) == ORDER_UPSCALE_INVALID_ARGUMENT);
    auto d = device(); auto c = config();
    CHECK(api.required_device_extensions(d.instance, d.physical_device, &count, &names, error, sizeof(error)) == ORDER_UPSCALE_OK);
    CHECK(count == 0 && names == nullptr);
    CHECK(api.required_device_extensions(VK_NULL_HANDLE, d.physical_device, &count, &names, error, sizeof(error)) == ORDER_UPSCALE_INVALID_ARGUMENT);
    void* ctx = handle<void*>(99);
    CHECK(api.create(nullptr, &c, &ctx, error, sizeof(error)) == ORDER_UPSCALE_INVALID_ARGUMENT && ctx == nullptr);
    CHECK(api.create(&d, &c, nullptr, error, sizeof(error)) == ORDER_UPSCALE_INVALID_ARGUMENT);
    auto invalid_config = [&](OrderUpscaleConfig bad) {
        ctx = handle<void*>(99); int before = creates;
        CHECK(api.create(&d, &bad, &ctx, error, sizeof(error)) == ORDER_UPSCALE_INVALID_ARGUMENT);
        CHECK(ctx == nullptr && creates == before && error[0]);
    };
    auto badc = c; badc.max_render_width = 0; invalid_config(badc);
    badc = c; badc.output_height = 0; invalid_config(badc);
    badc = c; badc.max_render_width = 4000; invalid_config(badc);
    badc = c; badc.output_width = 16385; invalid_config(badc);
    badc = c; badc.flags = 0x80000000u; invalid_config(badc);
    auto badd = d; badd.shader_storage_image_write_without_format_enabled = VK_FALSE;
    CHECK(api.create(&badd, &c, &ctx, error, sizeof(error)) == ORDER_UPSCALE_UNSUPPORTED && ctx == nullptr);
    badd = d; badd.get_instance_proc_addr = nullptr;
    CHECK(api.create(&badd, &c, &ctx, error, sizeof(error)) == ORDER_UPSCALE_INVALID_ARGUMENT && ctx == nullptr);
    badd = d; badd.graphics_queue_family = 1;
    CHECK(api.create(&badd, &c, &ctx, error, sizeof(error)) == ORDER_UPSCALE_INVALID_ARGUMENT && ctx == nullptr);
    queue_flags = VK_QUEUE_GRAPHICS_BIT;
    CHECK(api.create(&d, &c, &ctx, error, sizeof(error)) == ORDER_UPSCALE_UNSUPPORTED && ctx == nullptr);
    queue_flags |= VK_QUEUE_COMPUTE_BIT;
    api_version = VK_API_VERSION_1_1;
    CHECK(api.create(&d, &c, &ctx, error, sizeof(error)) == ORDER_UPSCALE_UNSUPPORTED && ctx == nullptr);
    api_version = VK_API_VERSION_1_2;
    create_result = FFX_VK_PORTABLE_ERROR_UNSUPPORTED;
    CHECK(api.create(&d, &c, &ctx, error, sizeof(error)) == ORDER_UPSCALE_UNSUPPORTED && ctx == nullptr);
    create_result = FFX_VK_PORTABLE_ERROR_BACKEND;
    char tiny[1] = {'x'};
    CHECK(api.create(&d, &c, &ctx, tiny, sizeof(tiny)) == ORDER_UPSCALE_BACKEND_ERROR && ctx == nullptr && tiny[0] == '\0');
    throw_create = true;
    CHECK(api.create(&d, &c, &ctx, error, sizeof(error)) == ORDER_UPSCALE_BACKEND_ERROR && ctx == nullptr);
    throw_create = false; create_result = FFX_VK_PORTABLE_OK;
    null_create = true;
    CHECK(api.create(&d, &c, &ctx, error, sizeof(error)) == ORDER_UPSCALE_BACKEND_ERROR && ctx == nullptr);
    null_create = false; partial_create = true; create_result = FFX_VK_PORTABLE_ERROR_BACKEND;
    int destroyed_before = destroys;
    CHECK(api.create(&d, &c, &ctx, error, sizeof(error)) == ORDER_UPSCALE_BACKEND_ERROR && ctx == nullptr);
    CHECK(destroys == destroyed_before + 1);
    partial_create = false; create_result = FFX_VK_PORTABLE_OK;
    c.flags |= ORDER_UPSCALE_DEPTH_INVERTED | ORDER_UPSCALE_DEPTH_INFINITE | ORDER_UPSCALE_MOTION_JITTERED;
    CHECK(api.create(&d, &c, &ctx, error, sizeof(error)) == ORDER_UPSCALE_OK && ctx && !error[0]);
    CHECK(seen_device.device == d.device && seen_device.getDeviceProcAddr == d.get_device_proc_addr);
    CHECK(seen_device.shaderStorageImageWriteWithoutFormatEnabled == VK_TRUE);
    CHECK(seen_device.shaderFloat16Enabled == VK_FALSE && seen_device.subgroupSizeControlEnabled == VK_FALSE);
    CHECK(seen_config.maxRenderSize.width == 1920 && seen_config.maxOutputSize.height == 2160);
    CHECK(seen_config.flags == (FFX_VK_PORTABLE_CONTEXT_HDR_COLOR_INPUT | FFX_VK_PORTABLE_CONTEXT_DEPTH_INVERTED |
        FFX_VK_PORTABLE_CONTEXT_DEPTH_INFINITE | FFX_VK_PORTABLE_CONTEXT_JITTERED_MOTION_VECTORS |
        FFX_VK_PORTABLE_CONTEXT_AUTO_EXPOSURE | FFX_VK_PORTABLE_CONTEXT_DYNAMIC_RESOLUTION));
    auto f = frame();
    CHECK(api.dispatch(nullptr, &f, error, sizeof(error)) == ORDER_UPSCALE_INVALID_ARGUMENT);
    CHECK(api.dispatch(ctx, nullptr, error, sizeof(error)) == ORDER_UPSCALE_INVALID_ARGUMENT);
    auto invalid_frame = [&](OrderUpscaleFrame bad) {
        int before = dispatches;
        CHECK(api.dispatch(ctx, &bad, error, sizeof(error)) == ORDER_UPSCALE_INVALID_ARGUMENT);
        CHECK(dispatches == before && error[0]);
    };
    auto badf = f; badf.command_buffer = VK_NULL_HANDLE; invalid_frame(badf);
    badf = f; badf.color.view = VK_NULL_HANDLE; invalid_frame(badf);
    badf = f; badf.depth.format = VK_FORMAT_D32_SFLOAT; invalid_frame(badf);
    badf = f; badf.motion.format = VK_FORMAT_R16G16B16A16_SFLOAT; invalid_frame(badf);
    badf = f; badf.color.usage = VK_IMAGE_USAGE_STORAGE_BIT; invalid_frame(badf);
    badf = f; badf.output.usage = VK_IMAGE_USAGE_SAMPLED_BIT; invalid_frame(badf);
    badf = f; badf.output.image = f.color.image; invalid_frame(badf);
    badf = f; badf.color.layout = VK_IMAGE_LAYOUT_GENERAL; invalid_frame(badf);
    badf = f; badf.output.layout = VK_IMAGE_LAYOUT_UNDEFINED; invalid_frame(badf);
    badf = f; badf.render_width = 1921; invalid_frame(badf);
    badf = f; badf.motion.width = 1919; invalid_frame(badf);
    badf = f; badf.output.height = 2161; invalid_frame(badf);
    badf = f; badf.frame_time_ms = 0; invalid_frame(badf);
    badf = f; badf.jitter_x = std::numeric_limits<float>::quiet_NaN(); invalid_frame(badf);
    badf = f; badf.motion_scale_y = 0; invalid_frame(badf);
    badf = f; badf.camera_near = -1; invalid_frame(badf);
    badf = f; badf.camera_far = std::numeric_limits<float>::infinity(); invalid_frame(badf);
    badf = f; badf.vertical_fov = 3.2f; invalid_frame(badf);
    badf = f; badf.pre_exposure = 0; invalid_frame(badf);
    badf = f; badf.reset_history = 2; invalid_frame(badf);
    float OrderUpscaleFrame::* const finite_fields[] = {
        &OrderUpscaleFrame::jitter_x, &OrderUpscaleFrame::jitter_y,
        &OrderUpscaleFrame::motion_scale_x, &OrderUpscaleFrame::motion_scale_y,
        &OrderUpscaleFrame::frame_time_ms, &OrderUpscaleFrame::pre_exposure,
        &OrderUpscaleFrame::camera_near, &OrderUpscaleFrame::camera_far, &OrderUpscaleFrame::vertical_fov};
    for (auto member : finite_fields) {
        badf = f; badf.*member = std::numeric_limits<float>::quiet_NaN(); invalid_frame(badf);
    }
    CHECK(api.dispatch(ctx, &f, error, sizeof(error)) == ORDER_UPSCALE_OK && !error[0]);
    CHECK(seen_frame.commandBuffer == f.command_buffer && seen_frame.color.image == f.color.image);
    CHECK(seen_frame.color.state == FFX_VK_PORTABLE_RESOURCE_STATE_COMPUTE_READ);
    CHECK(seen_frame.color.structSize == sizeof(FfxVkPortableImage) && seen_frame.color.mipCount == 1 &&
        seen_frame.color.arrayLayers == 1 && seen_frame.depth.aspect == VK_IMAGE_ASPECT_COLOR_BIT);
    CHECK(seen_frame.output.state == FFX_VK_PORTABLE_RESOURCE_STATE_UNORDERED_ACCESS);
    CHECK(seen_frame.depth.format == VK_FORMAT_R32_SFLOAT && seen_frame.motionVectors.format == VK_FORMAT_R16G16_SFLOAT);
    CHECK(seen_frame.jitterOffset.x == -0.125f && seen_frame.motionVectorScale.y == -1080);
    CHECK(seen_frame.frameTimeMilliseconds == 16.5f && seen_frame.preExposure == 1.25f);
    CHECK(seen_frame.cameraNear == 0.1f && seen_frame.cameraFar == 1000 && seen_frame.cameraVerticalFovRadians == 1.1f);
    CHECK(seen_frame.viewSpaceToMeters == 1 && seen_frame.reset == VK_TRUE && seen_frame.enableSharpening == VK_FALSE);
    CHECK(!seen_frame.exposure.image && !seen_frame.reactiveMask.image && !seen_frame.transparencyAndCompositionMask.image);
    CHECK(api.dispatch(ctx, &f, error, sizeof(error)) == ORDER_UPSCALE_OK && seen_frame.reset == VK_FALSE);
    f.reset_history = 1;
    CHECK(api.dispatch(ctx, &f, error, sizeof(error)) == ORDER_UPSCALE_OK && seen_frame.reset == VK_TRUE);
    f.reset_history = 0;
    dispatch_result = FFX_VK_PORTABLE_ERROR_BACKEND;
    CHECK(api.dispatch(ctx, &f, error, sizeof(error)) == ORDER_UPSCALE_BACKEND_ERROR && error[0]);
    dispatch_result = FFX_VK_PORTABLE_OK;
    CHECK(api.dispatch(ctx, &f, error, sizeof(error)) == ORDER_UPSCALE_OK && seen_frame.reset == VK_TRUE);
    throw_dispatch = true;
    CHECK(api.dispatch(ctx, &f, error, sizeof(error)) == ORDER_UPSCALE_BACKEND_ERROR);
    throw_dispatch = false;
    CHECK(api.dispatch(ctx, &f, error, sizeof(error)) == ORDER_UPSCALE_OK && seen_frame.reset == VK_TRUE);
    destroyed_before = destroys;
    api.destroy(ctx); api.destroy(nullptr); CHECK(destroys == destroyed_before + 1);
    c = config();
    CHECK(api.create(&d, &c, &ctx, nullptr, 0) == ORDER_UPSCALE_OK);
    badf = frame(); badf.camera_far = badf.camera_near; invalid_frame(badf);
    f = frame(); f.render_width = 1280; f.render_height = 720;
    CHECK(api.dispatch(ctx, &f, nullptr, 0) == ORDER_UPSCALE_OK);
    CHECK(seen_frame.renderSize.width == 1280 && seen_frame.renderSize.height == 720 && seen_frame.outputSize.width == 3840);
    throw_destroy = true;
    api.destroy(ctx);
    if (!failures) std::puts("FSR provider CPU contracts passed");
    return failures ? 1 : 0;
}
