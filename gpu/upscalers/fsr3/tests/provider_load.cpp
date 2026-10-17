#include "order1886_upscale.h"
#include <cstdio>

extern "C" OrderUpscaleStatus order1886_fsr_get_api(uint32_t, OrderUpscaleProviderApi*);

// Link/load the production DLL, but stop before any Vulkan/device work.
int main() {
    OrderUpscaleProviderApi api{};
    if (order1886_fsr_get_api(ORDER1886_UPSCALE_ABI, &api) != ORDER_UPSCALE_OK ||
        !api.create || !api.dispatch || !api.destroy || !api.name || !api.version) return 1;
    uint32_t count = 1;
    const char* const* names = nullptr;
    char error[128]{};
    if (api.required_instance_extensions(&count, &names, error, sizeof(error)) != ORDER_UPSCALE_OK ||
        count || names) return 2;
    void* context = reinterpret_cast<void*>(uintptr_t{1});
    if (api.create(nullptr, nullptr, &context, error, sizeof(error)) != ORDER_UPSCALE_INVALID_ARGUMENT ||
        context || !error[0]) return 3;
    if (api.dispatch(nullptr, nullptr, error, sizeof(error)) != ORDER_UPSCALE_INVALID_ARGUMENT) return 4;
    api.destroy(nullptr);
    std::printf("Loaded %s %s; production ABI/null contracts passed\n", api.name, api.version);
    return 0;
}
