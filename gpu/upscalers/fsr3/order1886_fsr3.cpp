#include "order1886_upscale.h"
#include "ffx_vk_portable.h"
#include <cmath>
#include <cstdio>
#include <memory>
#include <new>
#include <vector>

namespace {
constexpr uint32_t known_flags = ORDER_UPSCALE_HDR | ORDER_UPSCALE_DEPTH_INVERTED |
    ORDER_UPSCALE_DEPTH_INFINITE | ORDER_UPSCALE_MOTION_JITTERED;

struct Context {
    OrderUpscaleConfig config{};
    FfxVkPortableUpscaleContext* backend = nullptr;
    bool reset = true;
    ~Context() noexcept {
        try { if (backend) ffxVkPortableUpscaleContextDestroy(backend); } catch (...) {}
    }
};

OrderUpscaleStatus fail(OrderUpscaleStatus status, const char* message, char* error, size_t size) noexcept {
    if (error && size) std::snprintf(error, size, "%s", message);
    return status;
}

OrderUpscaleStatus backend_status(FfxVkPortableResult result, char* error, size_t size) noexcept {
    if (result == FFX_VK_PORTABLE_OK) return fail(ORDER_UPSCALE_OK, "", error, size);
    char message[96];
    std::snprintf(message, sizeof(message), "FSR 3.1.4 Vulkan backend error %d", static_cast<int>(result));
    OrderUpscaleStatus status = ORDER_UPSCALE_BACKEND_ERROR;
    if (result == FFX_VK_PORTABLE_ERROR_UNSUPPORTED) status = ORDER_UPSCALE_UNSUPPORTED;
    if (result == FFX_VK_PORTABLE_ERROR_INVALID_POINTER || result == FFX_VK_PORTABLE_ERROR_INVALID_ARGUMENT ||
        result == FFX_VK_PORTABLE_ERROR_INVALID_STRUCT_SIZE) status = ORDER_UPSCALE_INVALID_ARGUMENT;
    return fail(status, message, error, size);
}

OrderUpscaleStatus instance_extensions(uint32_t* count, const char* const** names,
                                     char* error, size_t size) noexcept {
    if (count) *count = 0;
    if (names) *names = nullptr;
    if (!count || !names) return fail(ORDER_UPSCALE_INVALID_ARGUMENT, "Extension output is null", error, size);
    // Vulkan 1.2 is required; no optional extension feature is presumed enabled.
    return fail(ORDER_UPSCALE_OK, "", error, size);
}

OrderUpscaleStatus device_extensions(VkInstance instance, VkPhysicalDevice physical,
    uint32_t* count, const char* const** names, char* error, size_t size) noexcept {
    const auto result = instance_extensions(count, names, error, size);
    if (result != ORDER_UPSCALE_OK) return result;
    if (!instance || !physical) return fail(ORDER_UPSCALE_INVALID_ARGUMENT, "Vulkan device query handles are null", error, size);
    return ORDER_UPSCALE_OK;
}

OrderUpscaleStatus create(const OrderUpscaleDevice* device, const OrderUpscaleConfig* config,
                         void** context, char* error, size_t size) noexcept {
    if (context) *context = nullptr;
    if (!context || !device || !config)
        return fail(ORDER_UPSCALE_INVALID_ARGUMENT, "Create argument is null", error, size);
    try {
        if (!config->max_render_width || !config->max_render_height || !config->output_width || !config->output_height ||
            config->max_render_width > config->output_width || config->max_render_height > config->output_height ||
            (config->flags & ~known_flags))
            return fail(ORDER_UPSCALE_INVALID_ARGUMENT, "Invalid upscale dimensions or flags", error, size);
        if (!device->instance || !device->physical_device || !device->device || !device->graphics_queue ||
            !device->get_instance_proc_addr || !device->get_device_proc_addr)
            return fail(ORDER_UPSCALE_INVALID_ARGUMENT, "Incomplete Vulkan device handles or loaders", error, size);
        if (device->shader_storage_image_write_without_format_enabled != VK_TRUE)
            return fail(ORDER_UPSCALE_UNSUPPORTED, "FSR requires enabled shaderStorageImageWriteWithoutFormat", error, size);
        const auto properties = reinterpret_cast<PFN_vkGetPhysicalDeviceProperties>(
            device->get_instance_proc_addr(device->instance, "vkGetPhysicalDeviceProperties"));
        const auto queues = reinterpret_cast<PFN_vkGetPhysicalDeviceQueueFamilyProperties>(
            device->get_instance_proc_addr(device->instance, "vkGetPhysicalDeviceQueueFamilyProperties"));
        if (!properties || !queues)
            return fail(ORDER_UPSCALE_UNSUPPORTED, "Vulkan physical-device queries unavailable", error, size);
        VkPhysicalDeviceProperties limits{};
        properties(device->physical_device, &limits);
        if (limits.apiVersion < VK_API_VERSION_1_2)
            return fail(ORDER_UPSCALE_UNSUPPORTED, "FSR provider requires Vulkan 1.2", error, size);
        if (config->output_width > limits.limits.maxImageDimension2D || config->output_height > limits.limits.maxImageDimension2D)
            return fail(ORDER_UPSCALE_INVALID_ARGUMENT, "Output exceeds Vulkan image limits", error, size);
        uint32_t count = 0;
        queues(device->physical_device, &count, nullptr);
        if (!count || device->graphics_queue_family >= count)
            return fail(ORDER_UPSCALE_INVALID_ARGUMENT, "Invalid graphics queue family", error, size);
        std::vector<VkQueueFamilyProperties> families(count);
        queues(device->physical_device, &count, families.data());
        if (device->graphics_queue_family >= count || !families[device->graphics_queue_family].queueCount ||
            !(families[device->graphics_queue_family].queueFlags & VK_QUEUE_COMPUTE_BIT))
            return fail(ORDER_UPSCALE_UNSUPPORTED, "Caller queue must support compute", error, size);

        auto result = std::make_unique<Context>();
        result->config = *config;
        FfxVkPortableDeviceInfo info{};
        info.structSize = sizeof(info);
        info.instance = device->instance;
        info.physicalDevice = device->physical_device;
        info.device = device->device;
        info.getDeviceProcAddr = device->get_device_proc_addr;
        info.queue = device->graphics_queue;
        info.queueFamilyIndex = device->graphics_queue_family;
        info.shaderStorageImageWriteWithoutFormatEnabled = VK_TRUE;
        FfxVkPortableUpscaleCreateInfo description{};
        description.structSize = sizeof(description);
        description.maxRenderSize = {config->max_render_width, config->max_render_height};
        description.maxOutputSize = {config->output_width, config->output_height};
        description.flags = FFX_VK_PORTABLE_CONTEXT_AUTO_EXPOSURE | FFX_VK_PORTABLE_CONTEXT_DYNAMIC_RESOLUTION;
        if (config->flags & ORDER_UPSCALE_HDR) description.flags |= FFX_VK_PORTABLE_CONTEXT_HDR_COLOR_INPUT;
        if (config->flags & ORDER_UPSCALE_DEPTH_INVERTED) description.flags |= FFX_VK_PORTABLE_CONTEXT_DEPTH_INVERTED;
        if (config->flags & ORDER_UPSCALE_DEPTH_INFINITE) description.flags |= FFX_VK_PORTABLE_CONTEXT_DEPTH_INFINITE;
        if (config->flags & ORDER_UPSCALE_MOTION_JITTERED) description.flags |= FFX_VK_PORTABLE_CONTEXT_JITTERED_MOTION_VECTORS;
        const auto status = backend_status(ffxVkPortableUpscaleContextCreate(&info, &description, &result->backend), error, size);
        if (status != ORDER_UPSCALE_OK) return status;
        if (!result->backend) return fail(ORDER_UPSCALE_BACKEND_ERROR, "FSR returned a null context", error, size);
        *context = result.release();
        return ORDER_UPSCALE_OK;
    } catch (...) {
        return fail(ORDER_UPSCALE_BACKEND_ERROR, "FSR context creation threw an exception", error, size);
    }
}

bool valid_image(const OrderUpscaleImage& image, VkFormat format, uint32_t w, uint32_t h,
                 uint32_t max_w, uint32_t max_h, bool output = false) noexcept {
    return image.image && image.view && image.format == format && image.width >= w && image.height >= h &&
        image.width <= max_w && image.height <= max_h &&
        (image.usage & (output ? VK_IMAGE_USAGE_STORAGE_BIT : VK_IMAGE_USAGE_SAMPLED_BIT)) &&
        image.layout == (output ? VK_IMAGE_LAYOUT_GENERAL : VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);
}

FfxVkPortableImage portable_image(const OrderUpscaleImage& image, bool output = false) noexcept {
    FfxVkPortableImage result{};
    result.structSize = sizeof(result);
    result.image = image.image;
    result.format = image.format;
    result.extent = {image.width, image.height};
    result.mipCount = 1;
    result.arrayLayers = 1;
    result.usage = image.usage;
    result.aspect = VK_IMAGE_ASPECT_COLOR_BIT;
    result.state = output ? FFX_VK_PORTABLE_RESOURCE_STATE_UNORDERED_ACCESS : FFX_VK_PORTABLE_RESOURCE_STATE_COMPUTE_READ;
    return result;
}

OrderUpscaleStatus dispatch(void* opaque, const OrderUpscaleFrame* frame, char* error, size_t size) noexcept {
    if (!opaque || !frame) return fail(ORDER_UPSCALE_INVALID_ARGUMENT, "Dispatch argument is null", error, size);
    auto& context = *static_cast<Context*>(opaque);
    try {
        const auto& c = context.config;
        const auto& f = *frame;
        if (!f.command_buffer || !f.render_width || !f.render_height || f.render_width > c.max_render_width ||
            f.render_height > c.max_render_height || f.reset_history > 1 ||
            !valid_image(f.color, VK_FORMAT_R16G16B16A16_SFLOAT, f.render_width, f.render_height, c.max_render_width, c.max_render_height) ||
            !valid_image(f.depth, VK_FORMAT_R32_SFLOAT, f.render_width, f.render_height, c.max_render_width, c.max_render_height) ||
            !valid_image(f.motion, VK_FORMAT_R16G16_SFLOAT, f.render_width, f.render_height, c.max_render_width, c.max_render_height) ||
            !valid_image(f.output, VK_FORMAT_R16G16B16A16_SFLOAT, c.output_width, c.output_height, c.output_width, c.output_height, true) ||
            f.output.image == f.color.image || f.output.image == f.depth.image || f.output.image == f.motion.image)
            return fail(ORDER_UPSCALE_INVALID_ARGUMENT, "Invalid FSR image, dimensions, layout or reset flag", error, size);
        const float values[] = {f.jitter_x, f.jitter_y, f.motion_scale_x, f.motion_scale_y, f.frame_time_ms,
            f.pre_exposure, f.camera_near, f.camera_far, f.vertical_fov};
        for (float value : values) if (!std::isfinite(value))
            return fail(ORDER_UPSCALE_INVALID_ARGUMENT, "FSR temporal input is not finite", error, size);
        if (f.motion_scale_x == 0 || f.motion_scale_y == 0 || f.frame_time_ms <= 0 || f.pre_exposure <= 0 ||
            f.camera_near <= 0 || f.camera_far < 0 || f.vertical_fov <= 0 || f.vertical_fov >= 3.14159265358979323846f ||
            (!(c.flags & ORDER_UPSCALE_DEPTH_INFINITE) && f.camera_far <= f.camera_near))
            return fail(ORDER_UPSCALE_INVALID_ARGUMENT, "Invalid FSR camera, motion scale, exposure or frame time", error, size);
        FfxVkPortableUpscaleDispatchInfo info{};
        info.structSize = sizeof(info);
        info.commandBuffer = f.command_buffer;
        info.color = portable_image(f.color);
        info.depth = portable_image(f.depth);
        info.motionVectors = portable_image(f.motion);
        info.output = portable_image(f.output, true);
        info.exposure.structSize = sizeof(info.exposure);
        info.reactiveMask.structSize = sizeof(info.reactiveMask);
        info.transparencyAndCompositionMask.structSize = sizeof(info.transparencyAndCompositionMask);
        info.jitterOffset = {f.jitter_x, f.jitter_y};
        info.motionVectorScale = {f.motion_scale_x, f.motion_scale_y};
        info.renderSize = {f.render_width, f.render_height};
        info.outputSize = {c.output_width, c.output_height};
        info.frameTimeMilliseconds = f.frame_time_ms;
        info.preExposure = f.pre_exposure;
        info.cameraNear = f.camera_near;
        info.cameraFar = f.camera_far;
        info.cameraVerticalFovRadians = f.vertical_fov;
        info.viewSpaceToMeters = 1.0f;
        info.reset = (context.reset || f.reset_history) ? VK_TRUE : VK_FALSE;
        // A failed recording may already contain commands: caller must discard it.
        context.reset = true;
        const auto status = backend_status(ffxVkPortableUpscaleContextRecordDispatch(context.backend, &info), error, size);
        if (status == ORDER_UPSCALE_OK) context.reset = false;
        return status;
    } catch (...) {
        context.reset = true;
        return fail(ORDER_UPSCALE_BACKEND_ERROR, "FSR dispatch threw an exception", error, size);
    }
}

void destroy(void* context) noexcept { delete static_cast<Context*>(context); }
} // namespace

extern "C"
#ifdef _WIN32
__declspec(dllexport)
#endif
OrderUpscaleStatus order1886_fsr_get_api(uint32_t abi, OrderUpscaleProviderApi* api) noexcept {
    if (!api) return ORDER_UPSCALE_INVALID_ARGUMENT;
    *api = {};
    if (abi != ORDER1886_UPSCALE_ABI) return ORDER_UPSCALE_UNSUPPORTED;
    *api = {ORDER1886_UPSCALE_ABI, "AMD FSR", "3.1.4 (FidelityFX SDK 1.1.4)",
        instance_extensions, device_extensions, create, dispatch, destroy};
    return ORDER_UPSCALE_OK;
}
