#include "../../shim/order1886_upscale.h"
#include <windows.h>
#include <cstdlib>
#include <cstring>
#include <iostream>

static void Check(bool value, const char* message) {
    if (!value) { std::cerr << message << '\n'; std::exit(1); }
}
static VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL MissingInstanceFunction(VkInstance, const char*) { return nullptr; }
static VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL MissingDeviceFunction(VkDevice, const char*) { return nullptr; }
int main(int argc, char** argv) {
    Check(argc == 2, "expected plugin path");
    auto module = LoadLibraryExA(argv[1], nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    Check(module != nullptr, "cannot load DLL");
    auto get_api = reinterpret_cast<OrderUpscaleGetApi>(GetProcAddress(module, "order1886_dlss_get_api"));
    Check(get_api != nullptr, "missing stable C export");
    OrderUpscaleProviderApi api{};
    Check(get_api(ORDER1886_UPSCALE_ABI, nullptr) == ORDER_UPSCALE_INVALID_ARGUMENT, "null API accepted");
    std::memset(&api, 0xff, sizeof(api));
    Check(get_api(ORDER1886_UPSCALE_ABI + 1, &api) == ORDER_UPSCALE_UNSUPPORTED, "unknown ABI accepted");
    Check(api.create == nullptr && api.abi_version == 0, "failed negotiation exposes callbacks");
    Check(get_api(ORDER1886_UPSCALE_ABI, &api) == ORDER_UPSCALE_OK, "ABI negotiation failed");
    Check(api.abi_version == ORDER1886_UPSCALE_ABI && api.name && api.version &&
          api.required_instance_extensions && api.required_device_extensions && api.create && api.dispatch && api.destroy,
          "incomplete provider table");
    char error[128]{};
    const char* const* names = reinterpret_cast<const char* const*>(1);
    uint32_t count = 1;
    Check(api.required_instance_extensions(nullptr, &names, error, sizeof(error)) == ORDER_UPSCALE_INVALID_ARGUMENT,
          "missing count accepted");
    Check(names == nullptr && error[0], "extension failure output not reset");
    Check(api.required_device_extensions({}, {}, &count, &names, error, sizeof(error)) == ORDER_UPSCALE_INVALID_ARGUMENT,
          "null device query accepted");
    Check(count == 0 && names == nullptr, "device extension failure output not reset");
    void* context = reinterpret_cast<void*>(1);
    Check(api.create(nullptr, nullptr, &context, error, sizeof(error)) == ORDER_UPSCALE_INVALID_ARGUMENT,
          "null create accepted");
    Check(context == nullptr && error[0], "failed create leaves a live context");
    OrderUpscaleDevice device{}; OrderUpscaleConfig config{1920,1080,3840,2160,0};
    context = reinterpret_cast<void*>(1);
    Check(api.create(&device, &config, &context, nullptr, 0) == ORDER_UPSCALE_INVALID_ARGUMENT && !context,
          "incomplete device accepted or context leaked");
    device.instance = reinterpret_cast<VkInstance>(1);
    device.physical_device = reinterpret_cast<VkPhysicalDevice>(1);
    device.device = reinterpret_cast<VkDevice>(1);
    device.graphics_queue = reinterpret_cast<VkQueue>(1);
    device.get_instance_proc_addr = MissingInstanceFunction;
    device.get_device_proc_addr = MissingDeviceFunction;
    context = reinterpret_cast<void*>(1);
    Check(api.create(&device, &config, &context, error, sizeof(error)) == ORDER_UPSCALE_UNSUPPORTED && !context,
          "missing Vulkan entrypoints accepted or failed create leaked context");
    char tiny[] = {'x','y'};
    Check(api.create(nullptr, nullptr, &context, tiny, 1) == ORDER_UPSCALE_INVALID_ARGUMENT &&
          tiny[0] == 0 && tiny[1] == 'y', "error buffer size contract violated");
    OrderUpscaleFrame frame{};
    Check(api.dispatch(nullptr, &frame, error, sizeof(error)) == ORDER_UPSCALE_INVALID_ARGUMENT, "null dispatch accepted");
    Check(api.dispatch(reinterpret_cast<void*>(1), &frame, error, sizeof(error)) == ORDER_UPSCALE_INVALID_ARGUMENT,
          "unknown context dereferenced");
    api.destroy(nullptr); api.destroy(reinterpret_cast<void*>(1));
    FreeLibrary(module);
    std::cout << "DLSS DLL C ABI contracts passed; no Vulkan/NGX initialization executed\n";
}
