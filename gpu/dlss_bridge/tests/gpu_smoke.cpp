// Reuse the existing static Vulkan upload/readback fixture; only DLSS loading and feature negotiation differ.
#include "../../shim/order1886_upscale.h"
#include <windows.h>
#include <bcrypt.h>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <vector>

#define VULKAN_FUNCTIONS(X) \
 X(vkGetInstanceProcAddr) X(vkGetDeviceProcAddr) X(vkCreateInstance) X(vkDestroyInstance) \
 X(vkEnumerateInstanceLayerProperties) X(vkEnumerateInstanceExtensionProperties) X(vkEnumeratePhysicalDevices) \
 X(vkGetPhysicalDeviceProperties) X(vkGetPhysicalDeviceProperties2) X(vkGetPhysicalDeviceFeatures) \
 X(vkGetPhysicalDeviceFeatures2) X(vkGetPhysicalDeviceQueueFamilyProperties) X(vkEnumerateDeviceExtensionProperties) \
 X(vkCreateDevice) X(vkDestroyDevice) X(vkGetDeviceQueue) X(vkDeviceWaitIdle) \
 X(vkGetPhysicalDeviceMemoryProperties) X(vkCreateBuffer) X(vkDestroyBuffer) X(vkGetBufferMemoryRequirements) \
 X(vkAllocateMemory) X(vkFreeMemory) X(vkBindBufferMemory) X(vkMapMemory) X(vkUnmapMemory) \
 X(vkCreateImage) X(vkDestroyImage) X(vkGetImageMemoryRequirements) X(vkBindImageMemory) \
 X(vkCreateImageView) X(vkDestroyImageView) X(vkCmdPipelineBarrier) X(vkCmdCopyBufferToImage) \
 X(vkCmdCopyImageToBuffer) X(vkCreateCommandPool) X(vkDestroyCommandPool) X(vkAllocateCommandBuffers) \
 X(vkResetCommandBuffer) X(vkBeginCommandBuffer) X(vkEndCommandBuffer) X(vkCreateFence) X(vkDestroyFence) \
 X(vkQueueSubmit) X(vkWaitForFences) X(vkResetFences)
#define DECLARE(name) static PFN_##name name{};
VULKAN_FUNCTIONS(DECLARE)
#undef DECLARE

static HMODULE VulkanModule{}, ProviderModule{};
static std::filesystem::path PluginPath;
static OrderUpscaleProviderApi RealApi{};
static bool InstanceCreated{}, DeviceCreated{}, RuntimeReported{};

static void load_vulkan() {
    VulkanModule = LoadLibraryExW(L"vulkan-1.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!VulkanModule) throw std::runtime_error("Cannot load system Vulkan loader");
#define LOAD(name) name = reinterpret_cast<PFN_##name>(GetProcAddress(VulkanModule,#name)); \
    if (!name) throw std::runtime_error("Vulkan loader missing " #name);
    VULKAN_FUNCTIONS(LOAD)
#undef LOAD
}

static void report_module(const wchar_t* name) {
    HMODULE module = GetModuleHandleW(name);
    if (!module) { std::printf("Runtime module %ls is not loaded\n",name); return; }
    wchar_t path[32768]{};
    if (!GetModuleFileNameW(module,path,32768)) throw std::runtime_error("Runtime module path unavailable");
    BCRYPT_ALG_HANDLE algorithm{}; BCRYPT_HASH_HANDLE hash{};
    if (BCryptOpenAlgorithmProvider(&algorithm,BCRYPT_SHA256_ALGORITHM,nullptr,0) < 0)
        throw std::runtime_error("SHA256 provider unavailable");
    DWORD object_size{}, bytes{}; BCryptGetProperty(algorithm,BCRYPT_OBJECT_LENGTH,
        reinterpret_cast<PUCHAR>(&object_size),sizeof(object_size),&bytes,0);
    std::vector<unsigned char> object(object_size);
    if (BCryptCreateHash(algorithm,&hash,object.data(),object_size,nullptr,0,0) < 0) {
        BCryptCloseAlgorithmProvider(algorithm,0); throw std::runtime_error("SHA256 creation failed");
    }
    std::ifstream file(std::filesystem::path(path),std::ios::binary);
    bool okay = bool(file); unsigned char buffer[65536];
    while (file) { file.read(reinterpret_cast<char*>(buffer),sizeof(buffer));
        if (file.gcount() && BCryptHashData(hash,buffer,ULONG(file.gcount()),0) < 0) {okay=false;break;} }
    unsigned char digest[32]{};
    okay = okay && file.eof() && BCryptFinishHash(hash,digest,sizeof(digest),0) >= 0;
    BCryptDestroyHash(hash); BCryptCloseAlgorithmProvider(algorithm,0);
    if (!okay) throw std::runtime_error("Cannot hash actual loaded NGX runtime");
    std::printf("Loaded runtime: %ls sha256=",path);
    for (auto value : digest) std::printf("%02x",value);
    DWORD ignored{}; const DWORD size = GetFileVersionInfoSizeW(path,&ignored);
    std::vector<unsigned char> version(size);
    VS_FIXEDFILEINFO* info{}; UINT info_size{};
    if (size && GetFileVersionInfoW(path,0,size,version.data()) &&
        VerQueryValueW(version.data(),L"\\",reinterpret_cast<void**>(&info),&info_size))
        std::printf(" version=%u.%u.%u.%u",HIWORD(info->dwFileVersionMS),LOWORD(info->dwFileVersionMS),
            HIWORD(info->dwFileVersionLS),LOWORD(info->dwFileVersionLS));
    std::puts("");
}

static void print_extensions(const char* phase,uint32_t count,const char* const* names) {
    std::printf("%s extensions (%u):",phase,count);
    for (uint32_t i=0;i<count;++i) std::printf(" %s",names[i]);
    std::puts("");
}
static OrderUpscaleStatus query_instance(uint32_t* count,const char* const** names,char* error,size_t size) {
    if (InstanceCreated) return ORDER_UPSCALE_BACKEND_ERROR;
    const auto status = RealApi.required_instance_extensions(count,names,error,size);
    if (status == ORDER_UPSCALE_OK) print_extensions("NGX required before instance creation",*count,*names);
    return status;
}
static OrderUpscaleStatus query_device(VkInstance instance,VkPhysicalDevice physical,
    uint32_t* count,const char* const** names,char* error,size_t size) {
    if (DeviceCreated) return ORDER_UPSCALE_BACKEND_ERROR;
    const auto status = RealApi.required_device_extensions(instance,physical,count,names,error,size);
    if (status == ORDER_UPSCALE_OK) print_extensions("NGX required before device creation",*count,*names);
    return status;
}
static OrderUpscaleStatus create_context(const OrderUpscaleDevice* device,const OrderUpscaleConfig* config,
    void** context,char* error,size_t size) {
    auto status = RealApi.create(device,config,context,error,size);
    std::printf("Production NGX init/capability create: status=%d error=%s\n",status,error);
    return status;
}
static OrderUpscaleStatus dispatch(void* context,const OrderUpscaleFrame* frame,char* error,size_t size) {
    auto actual = *frame;
    // NGX clears the output with a transfer operation; create_image provisions this usage below.
    actual.output.usage |= VK_IMAGE_USAGE_TRANSFER_DST_BIT;
    const auto status = RealApi.dispatch(context,&actual,error,size);
    std::printf("Production DLSS dispatch: status=%d reset=%u error=%s; requested preset=K; effective model unqueried\n",
        status,frame->reset_history,error);
    if (!RuntimeReported) { RuntimeReported=true; report_module(L"nvngx_dlss.dll"); report_module(L"_nvngx.dll"); }
    return status;
}
extern "C" OrderUpscaleStatus smoke_dlss_get_api(uint32_t abi,OrderUpscaleProviderApi* api) {
    ProviderModule = LoadLibraryExW(PluginPath.c_str(),nullptr,
        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    if (!ProviderModule) return ORDER_UPSCALE_BACKEND_ERROR;
    auto get_api = reinterpret_cast<OrderUpscaleGetApi>(GetProcAddress(ProviderModule,"order1886_dlss_get_api"));
    if (!get_api) return ORDER_UPSCALE_BACKEND_ERROR;
    auto status = get_api(abi,&RealApi);
    if (status != ORDER_UPSCALE_OK) return status;
    *api=RealApi; api->required_instance_extensions=query_instance; api->required_device_extensions=query_device;
    api->create=create_context; api->dispatch=dispatch;
    return status;
}

static VkResult create_instance(const VkInstanceCreateInfo* create,const VkAllocationCallbacks* allocator,VkInstance* instance) {
    bool validation=false,debug=false;
    for (uint32_t i=0;i<create->enabledLayerCount;++i)
        validation |= !std::strcmp(create->ppEnabledLayerNames[i],"VK_LAYER_KHRONOS_validation");
    for (uint32_t i=0;i<create->enabledExtensionCount;++i)
        debug |= !std::strcmp(create->ppEnabledExtensionNames[i],VK_EXT_DEBUG_UTILS_EXTENSION_NAME);
    if (!validation || !debug) throw std::runtime_error("Required Khronos validation layer/debug messenger unavailable");
    print_extensions("Actually enabled instance",create->enabledExtensionCount,create->ppEnabledExtensionNames);
    const auto status=vkCreateInstance(create,allocator,instance); InstanceCreated=status==VK_SUCCESS; return status;
}
static VkResult create_device(VkPhysicalDevice physical,const VkDeviceCreateInfo* input,
    const VkAllocationCallbacks* allocator,VkDevice* device) {
    VkPhysicalDeviceVulkan12Features supported12{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES};
    VkPhysicalDeviceVulkan11Features supported11{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_1_FEATURES};
    VkPhysicalDeviceFeatures2 supported{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2};
    supported.pNext=&supported11; supported11.pNext=&supported12;
    vkGetPhysicalDeviceFeatures2(physical,&supported);
    auto enabled=input->pEnabledFeatures ? *input->pEnabledFeatures : VkPhysicalDeviceFeatures{};
    enabled.shaderStorageImageReadWithoutFormat=supported.features.shaderStorageImageReadWithoutFormat;
    enabled.shaderStorageImageExtendedFormats=supported.features.shaderStorageImageExtendedFormats;
    enabled.shaderInt16=supported.features.shaderInt16;
    enabled.shaderInt64=supported.features.shaderInt64;
    VkPhysicalDeviceVulkan11Features enabled11{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_1_FEATURES};
    enabled11.storageBuffer16BitAccess=supported11.storageBuffer16BitAccess;
    enabled11.uniformAndStorageBuffer16BitAccess=supported11.uniformAndStorageBuffer16BitAccess;
    VkPhysicalDeviceVulkan12Features enabled12{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES};
    enabled12.shaderFloat16=supported12.shaderFloat16; enabled12.shaderInt8=supported12.shaderInt8;
    enabled12.bufferDeviceAddress=supported12.bufferDeviceAddress;
    enabled11.pNext=&enabled12; enabled12.pNext=const_cast<void*>(input->pNext);
    auto create=*input; create.pEnabledFeatures=&enabled; create.pNext=&enabled11;
    print_extensions("Actually enabled device",create.enabledExtensionCount,create.ppEnabledExtensionNames);
    std::printf("Enabled float16=%u int8=%u int16=%u int64=%u storage16=%u readWithoutFormat=%u writeWithoutFormat=%u bufferAddress=%u\n",
        enabled12.shaderFloat16,enabled12.shaderInt8,enabled.shaderInt16,enabled.shaderInt64,
        enabled11.storageBuffer16BitAccess,enabled.shaderStorageImageReadWithoutFormat,
        enabled.shaderStorageImageWriteWithoutFormat,enabled12.bufferDeviceAddress);
    const auto status=vkCreateDevice(physical,&create,allocator,device); DeviceCreated=status==VK_SUCCESS; return status;
}
static VkResult create_image(VkDevice device,const VkImageCreateInfo* input,
    const VkAllocationCallbacks* allocator,VkImage* image) {
    auto create = *input;
    if (create.usage & VK_IMAGE_USAGE_STORAGE_BIT) create.usage |= VK_IMAGE_USAGE_TRANSFER_DST_BIT;
    return vkCreateImage(device,&create,allocator,image);
}

#define order1886_fsr_get_api smoke_dlss_get_api
#define vkCreateInstance create_instance
#define vkCreateDevice create_device
#define vkCreateImage create_image
#define main unused_fsr_fixture_main
#include "../../upscalers/fsr3/tests/provider_gpu_smoke.cpp"
#undef main
#undef vkCreateImage
#undef vkCreateDevice
#undef vkCreateInstance
#undef order1886_fsr_get_api

int main(int argc,char** argv) {
    if (argc != 4 || std::strcmp(argv[1],"--run-gpu")) {
        std::fputs("Explicit opt-in: order_dlss_gpu_smoke --run-gpu ABSOLUTE_PLUGIN_DLL OUTPUT_DIRECTORY\n",stderr); return 2;
    }
    int result=1;
    try {
        PluginPath=std::filesystem::absolute(argv[2]); load_vulkan();
        run(argv[3]); result=validation_errors ? 1 : 0;
    } catch(const std::exception& error) {std::fprintf(stderr,"DLSS GPU smoke FAILED: %s\n",error.what());}
    if (ProviderModule) FreeLibrary(ProviderModule);
    if (VulkanModule) FreeLibrary(VulkanModule);
    std::printf("Final cleanup complete: validation_errors=%u validation_warnings=%u\n",validation_errors,validation_warnings);
    return result;
}
