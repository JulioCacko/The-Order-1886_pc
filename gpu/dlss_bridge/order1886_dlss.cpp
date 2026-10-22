#include "validation.h"
#include <windows.h>
#include <nvsdk_ngx_helpers_vk.h>
#include <array>
#include <cstring>
#include <mutex>
#include <new>
#include <utility>

namespace {
constexpr char ProjectId[] = "8cbe68e3-9aa9-414c-aa9e-a0a045df1886";
std::mutex Mutex;
struct Context {
    OrderUpscaleDevice device{};
    OrderUpscaleConfig config{};
    NVSDK_NGX_Parameter* parameters{};
    NVSDK_NGX_Handle* feature{};
    PFN_vkCmdPipelineBarrier barrier{};
    bool initialized{};
    bool first_frame{true};
    bool failed_recording{};
};
Context* Active{};
std::array<const char*, 64> InstanceNames{}, DeviceNames{};
std::array<VkExtensionProperties, 64> InstanceProperties{}, DeviceProperties{};

OrderUpscaleStatus Error(OrderUpscaleStatus status, char* error, size_t size,
                         const char* message) noexcept {
    order_dlss::Fail(error, size, message);
    return status;
}
OrderUpscaleStatus NgxError(const char* operation, NVSDK_NGX_Result result,
                            char* error, size_t size) noexcept {
    if (error && size) std::snprintf(error, size, "%s failed (NGX 0x%08x)", operation, unsigned(result));
    return ORDER_UPSCALE_BACKEND_ERROR;
}

bool PluginDirectory(wchar_t (&path)[MAX_PATH]) noexcept {
    HMODULE module{};
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                           GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           reinterpret_cast<LPCWSTR>(&PluginDirectory), &module)) return false;
    const DWORD length = GetModuleFileNameW(module, path, MAX_PATH);
    if (!length || length >= MAX_PATH) return false;
    auto* separator = wcsrchr(path, L'\\');
    if (!separator) return false;
    *separator = 0;
    return true;
}

NVSDK_NGX_FeatureDiscoveryInfo Discovery(const NVSDK_NGX_FeatureCommonInfo* common) noexcept {
    NVSDK_NGX_FeatureDiscoveryInfo info{};
    info.SDKVersion = NVSDK_NGX_Version_API;
    info.FeatureID = NVSDK_NGX_Feature_SuperSampling;
    info.Identifier.IdentifierType = NVSDK_NGX_Application_Identifier_Type_Project_Id;
    info.Identifier.v.ProjectDesc = {ProjectId, NVSDK_NGX_ENGINE_TYPE_CUSTOM, "1"};
    info.ApplicationDataPath = L".";
    info.FeatureInfo = common;
    return info;
}

OrderUpscaleStatus Extensions(VkInstance instance, VkPhysicalDevice physical,
                              bool device, uint32_t* count, const char* const** names,
                              char* error, size_t size) noexcept {
    if (count) *count = 0;
    if (names) *names = nullptr;
    if (!count || !names || (device && (!instance || !physical)))
        return Error(ORDER_UPSCALE_INVALID_ARGUMENT, error, size, "Missing DLSS extension query arguments");
    try {
        std::lock_guard<std::mutex> guard(Mutex);
        wchar_t directory[MAX_PATH]{};
        if (!PluginDirectory(directory))
            return Error(ORDER_UPSCALE_BACKEND_ERROR, error, size, "Cannot resolve DLSS plugin directory");
        const wchar_t* paths[] = {directory};
        NVSDK_NGX_FeatureCommonInfo common{};
        common.PathListInfo = {paths, 1};
        const auto info = Discovery(&common);
        VkExtensionProperties* properties{};
        uint32_t total{};
        const auto result = device
            ? NVSDK_NGX_VULKAN_GetFeatureDeviceExtensionRequirements(instance, physical, &info, &total, &properties)
            : NVSDK_NGX_VULKAN_GetFeatureInstanceExtensionRequirements(&info, &total, &properties);
        if (NVSDK_NGX_FAILED(result)) return NgxError("DLSS extension query", result, error, size);
        auto& copied = device ? DeviceProperties : InstanceProperties;
        auto& pointers = device ? DeviceNames : InstanceNames;
        if (total > copied.size() || (total && !properties))
            return Error(ORDER_UPSCALE_BACKEND_ERROR, error, size, "Invalid NGX extension list");
        for (uint32_t n = 0; n < total; ++n) {
            if (!std::memchr(properties[n].extensionName, 0, VK_MAX_EXTENSION_NAME_SIZE))
                return Error(ORDER_UPSCALE_BACKEND_ERROR, error, size, "Invalid NGX extension name");
            copied[n] = properties[n];
            pointers[n] = copied[n].extensionName;
        }
        *count = total;
        *names = total ? pointers.data() : nullptr;
        if (error && size) error[0] = 0;
        return ORDER_UPSCALE_OK;
    } catch (...) {
        return Error(ORDER_UPSCALE_BACKEND_ERROR, error, size, "Exception querying DLSS extensions");
    }
}
OrderUpscaleStatus InstanceExtensions(uint32_t* count, const char* const** names,
                                      char* error, size_t size) noexcept {
    return Extensions({}, {}, false, count, names, error, size);
}
OrderUpscaleStatus DeviceExtensions(VkInstance instance, VkPhysicalDevice physical,
                                    uint32_t* count, const char* const** names,
                                    char* error, size_t size) noexcept {
    return Extensions(instance, physical, true, count, names, error, size);
}

void Release(Context* context) noexcept {
    if (!context) return;
    if (context->feature) NVSDK_NGX_VULKAN_ReleaseFeature(context->feature);
    if (context->parameters) NVSDK_NGX_VULKAN_DestroyParameters(context->parameters);
    if (context->initialized) NVSDK_NGX_VULKAN_Shutdown1(context->device.device);
    delete context;
}

OrderUpscaleStatus Create(const OrderUpscaleDevice* device, const OrderUpscaleConfig* config,
                          void** output, char* error, size_t size) noexcept {
    if (output) *output = nullptr;
    if (!output || !device || !config || !device->instance || !device->physical_device ||
        !device->device || !device->get_instance_proc_addr || !device->get_device_proc_addr ||
        !device->graphics_queue)
        return Error(ORDER_UPSCALE_INVALID_ARGUMENT, error, size, "Invalid DLSS device/configuration");
    if (!order_dlss::ValidateConfig(*config, error, size)) return ORDER_UPSCALE_INVALID_ARGUMENT;
    Context* context{};
    std::unique_lock<std::mutex> guard(Mutex, std::defer_lock);
    try {
        guard.lock();
        if (Active) return Error(ORDER_UPSCALE_UNSUPPORTED, error, size, "Destroy the active DLSS context before creating another");
        const auto get_properties = reinterpret_cast<PFN_vkGetPhysicalDeviceProperties>(
            device->get_instance_proc_addr(device->instance, "vkGetPhysicalDeviceProperties"));
        const auto barrier = reinterpret_cast<PFN_vkCmdPipelineBarrier>(
            device->get_device_proc_addr(device->device, "vkCmdPipelineBarrier"));
        if (!get_properties || !barrier)
            return Error(ORDER_UPSCALE_UNSUPPORTED, error, size, "Required Vulkan entry points missing");
        VkPhysicalDeviceProperties properties{};
        get_properties(device->physical_device, &properties);
        if (properties.vendorID != 0x10de || properties.apiVersion < VK_API_VERSION_1_1 ||
            config->output_width > properties.limits.maxImageDimension2D ||
            config->output_height > properties.limits.maxImageDimension2D)
            return Error(ORDER_UPSCALE_UNSUPPORTED, error, size, "DLSS requires a supported NVIDIA GPU, Vulkan 1.1 and valid image limits");
        wchar_t directory[MAX_PATH]{}, data[MAX_PATH]{};
        const DWORD temp_length = GetTempPathW(MAX_PATH, data);
        if (!PluginDirectory(directory) || !temp_length || temp_length >= MAX_PATH)
            return Error(ORDER_UPSCALE_BACKEND_ERROR, error, size, "Cannot resolve DLSS runtime/data directory");
        const wchar_t* paths[] = {directory};
        NVSDK_NGX_FeatureCommonInfo common{};
        common.PathListInfo = {paths, 1};
        context = new (std::nothrow) Context;
        if (!context) return Error(ORDER_UPSCALE_BACKEND_ERROR, error, size, "DLSS context allocation failed");
        context->device = *device; context->config = *config; context->barrier = barrier;
        auto result = NVSDK_NGX_VULKAN_Init_with_ProjectID(ProjectId, NVSDK_NGX_ENGINE_TYPE_CUSTOM, "1",
            data, device->instance, device->physical_device, device->device,
            device->get_instance_proc_addr, device->get_device_proc_addr, &common);
        if (NVSDK_NGX_FAILED(result)) { Release(context); return NgxError("DLSS NGX initialization", result, error, size); }
        context->initialized = true;
        result = NVSDK_NGX_VULKAN_GetCapabilityParameters(&context->parameters);
        if (NVSDK_NGX_FAILED(result)) { Release(context); return NgxError("DLSS capabilities", result, error, size); }
        int available{}, driver{};
        const auto capability = context->parameters->Get(NVSDK_NGX_Parameter_SuperSampling_Available, &available);
        context->parameters->Get(NVSDK_NGX_Parameter_SuperSampling_NeedsUpdatedDriver, &driver);
        if (NVSDK_NGX_FAILED(capability) || !available || driver) {
            Release(context);
            return Error(ORDER_UPSCALE_UNSUPPORTED, error, size, driver ? "Update NVIDIA driver for DLSS" : "DLSS Super Resolution unavailable");
        }
        const char* presets[] = {NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_DLAA,
            NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_Quality, NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_Balanced,
            NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_Performance, NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_UltraPerformance};
        for (const auto* preset : presets)
            context->parameters->Set(preset, unsigned(NVSDK_NGX_DLSS_Hint_Render_Preset_K));
        context->parameters->Set(NVSDK_NGX_Parameter_FreeMemOnReleaseFeature, 1u);
        Active = context;
        *output = context;
        if (error && size) error[0] = 0;
        return ORDER_UPSCALE_OK;
    } catch (...) {
        Release(context);
        return Error(ORDER_UPSCALE_BACKEND_ERROR, error, size, "Exception creating DLSS context");
    }
}

NVSDK_NGX_Resource_VK Resource(const OrderUpscaleImage& image, bool output) noexcept {
    const VkImageSubresourceRange range{VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    return NVSDK_NGX_Create_ImageView_Resource_VK(image.view, image.image, range,
                                                 image.format, image.width, image.height, output);
}

OrderUpscaleStatus Dispatch(void* pointer, const OrderUpscaleFrame* frame,
                            char* error, size_t size) noexcept {
    if (!pointer || !frame) return Error(ORDER_UPSCALE_INVALID_ARGUMENT, error, size, "Missing DLSS context/frame");
    std::unique_lock<std::mutex> guard(Mutex, std::defer_lock);
    try {
        guard.lock();
        if (pointer != Active) return Error(ORDER_UPSCALE_INVALID_ARGUMENT, error, size, "Unknown DLSS context");
        auto& context = *Active;
        if (context.failed_recording)
            return Error(ORDER_UPSCALE_BACKEND_ERROR, error, size, "Previous DLSS recording failed; destroy/recreate context before dispatch");
        if (!order_dlss::ValidateFrame(*frame, context.config, error, size)) return ORDER_UPSCALE_INVALID_ARGUMENT;
        if (!context.feature) {
            NVSDK_NGX_DLSS_Create_Params create{};
            const float ratio = float(context.config.max_render_width) / context.config.output_width;
            const auto quality = ratio <= 0.34f ? NVSDK_NGX_PerfQuality_Value_UltraPerformance :
                ratio <= 0.50f ? NVSDK_NGX_PerfQuality_Value_MaxPerf :
                ratio <= 0.59f ? NVSDK_NGX_PerfQuality_Value_Balanced :
                ratio < 0.99f ? NVSDK_NGX_PerfQuality_Value_MaxQuality : NVSDK_NGX_PerfQuality_Value_DLAA;
            create.Feature = {context.config.max_render_width, context.config.max_render_height,
                context.config.output_width, context.config.output_height, quality};
            create.InFeatureCreateFlags = NVSDK_NGX_DLSS_Feature_Flags_MVLowRes | NVSDK_NGX_DLSS_Feature_Flags_AutoExposure;
            if (context.config.flags & ORDER_UPSCALE_HDR) create.InFeatureCreateFlags |= NVSDK_NGX_DLSS_Feature_Flags_IsHDR;
            if (context.config.flags & ORDER_UPSCALE_DEPTH_INVERTED) create.InFeatureCreateFlags |= NVSDK_NGX_DLSS_Feature_Flags_DepthInverted;
            if (context.config.flags & ORDER_UPSCALE_MOTION_JITTERED) create.InFeatureCreateFlags |= NVSDK_NGX_DLSS_Feature_Flags_MVJittered;
            const auto result = NGX_VULKAN_CREATE_DLSS_EXT1(context.device.device, frame->command_buffer,
                                                           1, 1, &context.feature, context.parameters, &create);
            if (NVSDK_NGX_FAILED(result)) {
                context.failed_recording = true;
                if (context.feature) { NVSDK_NGX_VULKAN_ReleaseFeature(context.feature); context.feature = nullptr; }
                return NgxError("DLSS feature creation (discard recording and recreate context)", result, error, size);
            }
        }
        const OrderUpscaleImage* images[] = {&frame->color, &frame->depth, &frame->motion, &frame->output};
        std::array<VkImageMemoryBarrier, 4> barriers{};
        for (size_t n = 0; n < barriers.size(); ++n) {
            auto& b = barriers[n]; b.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
            b.srcAccessMask = VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_MEMORY_WRITE_BIT;
            b.dstAccessMask = n == 3 ? VK_ACCESS_SHADER_WRITE_BIT | VK_ACCESS_TRANSFER_WRITE_BIT : VK_ACCESS_SHADER_READ_BIT;
            b.oldLayout = images[n]->layout;
            b.newLayout = n == 3 ? VK_IMAGE_LAYOUT_GENERAL : VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
            b.srcQueueFamilyIndex = b.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
            b.image = images[n]->image;
            b.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
        }
        // NGX uses both compute shaders and transfer clears, including on the caller's output image.
        constexpr VkPipelineStageFlags ngx_stages = VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT | VK_PIPELINE_STAGE_TRANSFER_BIT;
        context.barrier(frame->command_buffer, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, ngx_stages,
                         0, 0, nullptr, 0, nullptr, uint32_t(barriers.size()), barriers.data());
        auto color = Resource(frame->color, false), depth = Resource(frame->depth, false);
        auto motion = Resource(frame->motion, false), output = Resource(frame->output, true);
        NVSDK_NGX_VK_DLSS_Eval_Params eval{};
        eval.Feature.pInColor = &color; eval.Feature.pInOutput = &output;
        eval.pInDepth = &depth; eval.pInMotionVectors = &motion;
        eval.InJitterOffsetX = frame->jitter_x; eval.InJitterOffsetY = frame->jitter_y;
        eval.InRenderSubrectDimensions = {frame->render_width, frame->render_height};
        eval.InReset = frame->reset_history || context.first_frame;
        eval.InMVScaleX = frame->motion_scale_x; eval.InMVScaleY = frame->motion_scale_y;
        eval.InPreExposure = frame->pre_exposure; eval.InExposureScale = 1;
        eval.InFrameTimeDeltaInMsec = frame->frame_time_ms;
        const auto result = NGX_VULKAN_EVALUATE_DLSS_EXT(frame->command_buffer, context.feature, context.parameters, &eval);
        for (size_t n = 0; n < barriers.size(); ++n) {
            auto& b = barriers[n];
            b.srcAccessMask = b.dstAccessMask;
            b.dstAccessMask = VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_MEMORY_WRITE_BIT;
            std::swap(b.oldLayout, b.newLayout);
        }
        context.barrier(frame->command_buffer, ngx_stages, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,
                         0, 0, nullptr, 0, nullptr, uint32_t(barriers.size()), barriers.data());
        if (NVSDK_NGX_FAILED(result)) {
            // Feature creation records GPU initialization; a discarded recording cannot leave a reusable feature.
            context.failed_recording = true;
            return NgxError("DLSS evaluation (discard recording and recreate context)", result, error, size);
        }
        context.first_frame = false;
        if (error && size) error[0] = 0;
        return ORDER_UPSCALE_OK;
    } catch (...) {
        if (guard.owns_lock() && pointer == Active) Active->failed_recording = true;
        return Error(ORDER_UPSCALE_BACKEND_ERROR, error, size, "Exception dispatching DLSS (discard recording and recreate context)");
    }
}

void Destroy(void* pointer) noexcept {
    if (!pointer) return;
    try {
        std::lock_guard<std::mutex> guard(Mutex);
        if (pointer == Active) { auto* context = Active; Active = nullptr; Release(context); }
    } catch (...) {}
}
}

extern "C" __declspec(dllexport) OrderUpscaleStatus order1886_dlss_get_api(
    uint32_t abi, OrderUpscaleProviderApi* api) noexcept {
    if (!api) return ORDER_UPSCALE_INVALID_ARGUMENT;
    *api = {};
    if (abi != ORDER1886_UPSCALE_ABI) return ORDER_UPSCALE_UNSUPPORTED;
    *api = {ORDER1886_UPSCALE_ABI, "DLSS", "310.9.16 / preset K", InstanceExtensions,
             DeviceExtensions, Create, Dispatch, Destroy};
    return ORDER_UPSCALE_OK;
}
