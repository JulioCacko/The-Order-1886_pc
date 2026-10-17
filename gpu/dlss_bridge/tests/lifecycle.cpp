#include "../../shim/order1886_upscale.h"
#include <nvsdk_ngx_helpers_vk.h>
#include <cstdlib>
#include <cstring>
#include <iostream>

extern "C" OrderUpscaleStatus order1886_dlss_get_api(uint32_t, OrderUpscaleProviderApi*) noexcept;
namespace {
int Creates{}, Evaluations{}, Releases{}, Shutdowns{}, Barriers{}, LastReset{};
bool FailCreate{}, FailEvaluate{};
void Check(bool value, const char* message) {
    if (!value) { std::cerr << message << '\n'; std::exit(1); }
}
struct Parameters : NVSDK_NGX_Parameter {
#define FAKE_PARAMETER(TYPE) \
    void Set(const char*, TYPE) override {} \
    NVSDK_NGX_Result Get(const char*, TYPE* value) const override { *value = {}; return NVSDK_NGX_Result_Success; }
    FAKE_PARAMETER(unsigned long long)
    FAKE_PARAMETER(float)
    FAKE_PARAMETER(double)
    FAKE_PARAMETER(unsigned int)
    FAKE_PARAMETER(ID3D11Resource*)
    FAKE_PARAMETER(ID3D12Resource*)
    FAKE_PARAMETER(void*)
#undef FAKE_PARAMETER
    void Set(const char* name, int value) override {
        if (!std::strcmp(name, NVSDK_NGX_Parameter_Reset)) LastReset = value;
    }
    NVSDK_NGX_Result Get(const char* name, int* value) const override {
        *value = !std::strcmp(name, NVSDK_NGX_Parameter_SuperSampling_Available);
        return NVSDK_NGX_Result_Success;
    }
    void Reset() override {}
} Params;
VKAPI_ATTR void VKAPI_CALL Properties(VkPhysicalDevice, VkPhysicalDeviceProperties* properties) {
    *properties = {}; properties->vendorID = 0x10de;
    properties->apiVersion = VK_API_VERSION_1_1; properties->limits.maxImageDimension2D = 16384;
}
VKAPI_ATTR void VKAPI_CALL Barrier(VkCommandBuffer, VkPipelineStageFlags source, VkPipelineStageFlags destination,
    VkDependencyFlags, uint32_t, const VkMemoryBarrier*, uint32_t, const VkBufferMemoryBarrier*,
    uint32_t count, const VkImageMemoryBarrier* barriers) {
    Check(count == 4, "expected input/output barriers");
    if (source == VK_PIPELINE_STAGE_ALL_COMMANDS_BIT)
        Check((destination & VK_PIPELINE_STAGE_TRANSFER_BIT) &&
              (barriers[3].dstAccessMask & VK_ACCESS_TRANSFER_WRITE_BIT),
              "NGX output clear not synchronized before evaluation");
    else
        Check((source & VK_PIPELINE_STAGE_TRANSFER_BIT) &&
              (barriers[3].srcAccessMask & VK_ACCESS_TRANSFER_WRITE_BIT),
              "NGX output clear not synchronized after evaluation");
    ++Barriers;
}
VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL InstanceFunction(VkInstance, const char* name) {
    return !std::strcmp(name, "vkGetPhysicalDeviceProperties") ? reinterpret_cast<PFN_vkVoidFunction>(Properties) : nullptr;
}
VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL DeviceFunction(VkDevice, const char* name) {
    return !std::strcmp(name, "vkCmdPipelineBarrier") ? reinterpret_cast<PFN_vkVoidFunction>(Barrier) : nullptr;
}
OrderUpscaleFrame Frame() {
    OrderUpscaleFrame frame{};
    frame.command_buffer = reinterpret_cast<VkCommandBuffer>(1);
    auto image = [](uintptr_t id, VkFormat format, VkImageUsageFlags usage, uint32_t w, uint32_t h) {
        return OrderUpscaleImage{reinterpret_cast<VkImage>(id), reinterpret_cast<VkImageView>(id), format,
                                  w, h, usage, VK_IMAGE_LAYOUT_GENERAL};
    };
    frame.color = image(1, VK_FORMAT_R16G16B16A16_SFLOAT, VK_IMAGE_USAGE_SAMPLED_BIT, 1920,1080);
    frame.depth = image(2, VK_FORMAT_R32_SFLOAT, VK_IMAGE_USAGE_SAMPLED_BIT,1920,1080);
    frame.motion = image(3, VK_FORMAT_R16G16_SFLOAT, VK_IMAGE_USAGE_SAMPLED_BIT,1920,1080);
    frame.output = image(4, VK_FORMAT_R16G16B16A16_SFLOAT,
        VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT,3840,2160);
    frame.render_width = 1920; frame.render_height = 1080;
    frame.motion_scale_x = frame.motion_scale_y = frame.pre_exposure = 1;
    frame.frame_time_ms = 16.67f; frame.camera_near = 0.1f;
    frame.camera_far = 1000; frame.vertical_fov = 1;
    return frame;
}
}

extern "C" {
void NVSDK_CONV NVSDK_NGX_Parameter_SetUI(NVSDK_NGX_Parameter* p, const char* name, unsigned value) { p->Set(name,value); }
void NVSDK_CONV NVSDK_NGX_Parameter_SetI(NVSDK_NGX_Parameter* p, const char* name, int value) { p->Set(name,value); }
void NVSDK_CONV NVSDK_NGX_Parameter_SetF(NVSDK_NGX_Parameter* p, const char* name, float value) { p->Set(name,value); }
void NVSDK_CONV NVSDK_NGX_Parameter_SetVoidPointer(NVSDK_NGX_Parameter* p, const char* name, void* value) { p->Set(name,value); }
NVSDK_NGX_Result NVSDK_CONV NVSDK_NGX_VULKAN_Init_with_ProjectID(const char*, NVSDK_NGX_EngineType,
    const char*, const wchar_t*, VkInstance, VkPhysicalDevice, VkDevice, PFN_vkGetInstanceProcAddr,
    PFN_vkGetDeviceProcAddr, const NVSDK_NGX_FeatureCommonInfo*, NVSDK_NGX_Version) { return NVSDK_NGX_Result_Success; }
NVSDK_NGX_Result NVSDK_CONV NVSDK_NGX_VULKAN_GetCapabilityParameters(NVSDK_NGX_Parameter** p) {
    *p = &Params; return NVSDK_NGX_Result_Success;
}
NVSDK_NGX_Result NVSDK_CONV NVSDK_NGX_VULKAN_DestroyParameters(NVSDK_NGX_Parameter*) { return NVSDK_NGX_Result_Success; }
NVSDK_NGX_Result NVSDK_CONV NVSDK_NGX_VULKAN_Shutdown1(VkDevice) { ++Shutdowns; return NVSDK_NGX_Result_Success; }
NVSDK_NGX_Result NVSDK_CONV NVSDK_NGX_VULKAN_ReleaseFeature(NVSDK_NGX_Handle* handle) {
    Check(handle != nullptr, "releasing null feature"); ++Releases; return NVSDK_NGX_Result_Success;
}
NVSDK_NGX_Result NVSDK_CONV NVSDK_NGX_VULKAN_CreateFeature1(VkDevice, VkCommandBuffer,
    NVSDK_NGX_Feature feature, NVSDK_NGX_Parameter*, NVSDK_NGX_Handle** handle) {
    Check(feature == NVSDK_NGX_Feature_SuperSampling, "non-SR feature requested");
    *handle = reinterpret_cast<NVSDK_NGX_Handle*>(uintptr_t(++Creates));
    return FailCreate ? NVSDK_NGX_Result_FAIL_PlatformError : NVSDK_NGX_Result_Success;
}
NVSDK_NGX_Result NVSDK_CONV NVSDK_NGX_VULKAN_CreateFeature(VkCommandBuffer buffer, NVSDK_NGX_Feature feature,
    NVSDK_NGX_Parameter* params, NVSDK_NGX_Handle** handle) {
    return NVSDK_NGX_VULKAN_CreateFeature1({},buffer,feature,params,handle);
}
NVSDK_NGX_Result NVSDK_CONV NVSDK_NGX_VULKAN_EvaluateFeature_C(VkCommandBuffer,
    const NVSDK_NGX_Handle*, const NVSDK_NGX_Parameter*, PFN_NVSDK_NGX_ProgressCallback_C) {
    ++Evaluations; return FailEvaluate ? NVSDK_NGX_Result_FAIL_PlatformError : NVSDK_NGX_Result_Success;
}
NVSDK_NGX_Result NVSDK_CONV NVSDK_NGX_VULKAN_GetFeatureInstanceExtensionRequirements(
    const NVSDK_NGX_FeatureDiscoveryInfo*, uint32_t* count, VkExtensionProperties** properties) {
    *count = 0; *properties = nullptr; return NVSDK_NGX_Result_Success;
}
NVSDK_NGX_Result NVSDK_CONV NVSDK_NGX_VULKAN_GetFeatureDeviceExtensionRequirements(VkInstance,
    VkPhysicalDevice, const NVSDK_NGX_FeatureDiscoveryInfo* info, uint32_t* count, VkExtensionProperties** properties) {
    return NVSDK_NGX_VULKAN_GetFeatureInstanceExtensionRequirements(info,count,properties);
}
}

int main() {
    OrderUpscaleProviderApi api{};
    Check(order1886_dlss_get_api(ORDER1886_UPSCALE_ABI,&api) == ORDER_UPSCALE_OK, "missing ABI");
    OrderUpscaleDevice device{reinterpret_cast<VkInstance>(1),reinterpret_cast<VkPhysicalDevice>(1),
        reinterpret_cast<VkDevice>(1),InstanceFunction,DeviceFunction,reinterpret_cast<VkQueue>(1),0};
    OrderUpscaleConfig config{1920,1080,3840,2160,ORDER_UPSCALE_HDR};
    auto frame = Frame(); char error[256]{};
    for (int scenario = 0; scenario < 2; ++scenario) {
        void* context{};
        Check(api.create(&device,&config,&context,error,sizeof(error)) == ORDER_UPSCALE_OK, "mock create failed");
        FailCreate = scenario == 0; FailEvaluate = scenario == 1;
        Check(api.dispatch(context,&frame,error,sizeof(error)) == ORDER_UPSCALE_BACKEND_ERROR, "injected failure ignored");
        FailCreate = FailEvaluate = false;
        const int creations = Creates, evaluations = Evaluations, barriers = Barriers;
        Check(api.dispatch(context,&frame,error,sizeof(error)) == ORDER_UPSCALE_BACKEND_ERROR,
              "context reused after its feature initialization recording was discarded");
        Check(Creates == creations && Evaluations == evaluations && Barriers == barriers,
              "poisoned context recorded more NGX/GPU work");
        api.destroy(context); context = nullptr;
        Check(api.create(&device,&config,&context,error,sizeof(error)) == ORDER_UPSCALE_OK, "mock recreation failed");
        Check(api.dispatch(context,&frame,error,sizeof(error)) == ORDER_UPSCALE_OK, "fresh context failed after recovery");
        Check(Creates == creations + 1 && Evaluations == evaluations + 1 && LastReset == 1,
              "recovery did not create a fresh feature and reset its history");
        api.destroy(context);
    }
    Check(Releases == 4 && Shutdowns == 4, "NGX recovery leaked a feature/context");
    std::cout << "DLSS lifecycle passed: create/evaluate failures reject retry; recreation succeeds; fake NGX/Vulkan only\n";
}
