// SPDX-License-Identifier: GPL-2.0-or-later
// See vk_upscale_providers.h.

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <vector>
#include "ps4_settings.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_upscale_providers.h"
#ifdef _WIN32
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif

namespace Vulkan {

namespace {

std::filesystem::path RuntimeDirectory() {
#ifdef _WIN32
    wchar_t path[MAX_PATH]{};
    const DWORD size = GetModuleFileNameW(nullptr, path, MAX_PATH);
    return std::filesystem::path(std::wstring(path, size)).parent_path();
#else
    return std::filesystem::current_path();
#endif
}

std::vector<UpscaleProvider>& Providers() {
    static std::vector<UpscaleProvider> list{
        {.key = "fsr3", .library = "order1886_fsr3.dll", .symbol = "order1886_fsr_get_api"},
        {.key = "dlss", .library = "order1886_dlss.dll", .symbol = "order1886_dlss_get_api"},
    };
    return list;
}

/// The DLL and its ABI, once. The module stays loaded for the whole process: the runtime keeps
/// pointers to the provider's extension names and functions.
bool Load(UpscaleProvider& provider) {
    if (provider.loaded || !provider.reason.empty()) {
        return provider.loaded;
    }
#ifdef _WIN32
    const auto path = RuntimeDirectory() / provider.library;
    if (!std::filesystem::exists(path)) {
        provider.reason = std::string(provider.library) + " is not next to the runtime";
        return false;
    }
    HMODULE module = LoadLibraryExW(path.c_str(), nullptr,
                                    LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    if (!module) {
        provider.reason = std::string(provider.library) + " failed to load (error " +
                          std::to_string(GetLastError()) + ")";
        return false;
    }
    const auto get_api = reinterpret_cast<OrderUpscaleGetApi>(
        reinterpret_cast<void*>(GetProcAddress(module, provider.symbol)));
    if (!get_api) {
        provider.reason = std::string(provider.library) + " does not export " + provider.symbol;
        return false;
    }
    if (get_api(ORDER1886_UPSCALE_ABI, &provider.api) != ORDER_UPSCALE_OK ||
        provider.api.abi_version != ORDER1886_UPSCALE_ABI) {
        provider.reason = "provider does not implement ABI " + std::to_string(ORDER1886_UPSCALE_ABI);
        return false;
    }
    provider.name = provider.api.name ? provider.api.name : provider.key;
    provider.version = provider.api.version ? provider.api.version : "";
    provider.loaded = true;
    return true;
#else
    provider.reason = "providers are Windows DLLs";
    return false;
#endif
}

UpscaleProvider* Selected() {
    const int requested = Ps4Settings::Get().requested_upscaler;
    if (requested == Ps4Settings::UpscalerOff) {
        return nullptr;
    }
    const std::string_view key = Ps4Settings::UpscalerName(requested);
    for (auto& provider : Providers()) {
        if (key == provider.key) {
            return Load(provider) ? &provider : nullptr;
        }
    }
    return nullptr;
}

void Check(UpscaleProvider& provider, const Instance& instance) {
    if (!Load(provider)) {
        return;
    }
    // A provider that was not selected never had its extensions enabled; one that needs none is
    // usable either way.
    u32 count = 0;
    const char* const* names = nullptr;
    char error[256]{};
    // A provider that cannot say which extensions it needs cannot be trusted to start.
    if (provider.api.required_instance_extensions &&
        provider.api.required_instance_extensions(&count, &names, error, sizeof(error)) !=
            ORDER_UPSCALE_OK) {
        provider.reason = std::string("cannot list its instance extensions: ") + error;
        return;
    }
    if (count != 0 && !provider.instance_extensions_enabled) {
        provider.reason = provider.instance_extensions.empty()
                              ? "needs Vulkan instance extensions, which are enabled only when it is "
                                "the selected upscaler"
                              : "the Vulkan instance does not offer every extension it needs";
        return;
    }
    count = 0;
    if (provider.api.required_device_extensions &&
        provider.api.required_device_extensions(instance.GetInstance(), instance.GetPhysicalDevice(),
                                                &count, &names, error, sizeof(error)) !=
            ORDER_UPSCALE_OK) {
        provider.reason = std::string("cannot list its device extensions: ") + error;
        return;
    }
    if (count != 0 && !provider.device_extensions_enabled) {
        std::string missing;
        const auto available = instance.GetAvailableExtensions();
        for (u32 i = 0; i < count; ++i) {
            const bool offered = std::ranges::find(available, std::string(names[i])) != available.end();
            missing += (missing.empty() ? "" : ", ") + std::string(names[i]) +
                       (offered ? " (offered, enabled only when it is the selected upscaler)"
                                : " (not offered by the GPU)");
        }
        provider.reason = "needs device extensions " + missing;
        return;
    }
    if (!instance.IsStorageImageWriteWithoutFormatEnabled()) {
        provider.reason = "shaderStorageImageWriteWithoutFormat is not enabled on this device";
        return;
    }
    provider.available = true;
}

} // namespace

std::vector<const char*> SelectedProviderInstanceExtensions(
    std::span<const VkExtensionProperties> available) {
    UpscaleProvider* provider = Selected();
    if (!provider || !provider->api.required_instance_extensions) {
        return {};
    }
    u32 count = 0;
    const char* const* names = nullptr;
    char error[256]{};
    if (provider->api.required_instance_extensions(&count, &names, error, sizeof(error)) !=
        ORDER_UPSCALE_OK) {
        std::printf("Upscaler provider %s: cannot list its instance extensions (%s)\n",
                    provider->key, error);
        return {};
    }
    std::vector<const char*> enabled;
    for (u32 i = 0; i < count; ++i) {
        provider->instance_extensions.emplace_back(names[i]);
        const bool offered = std::ranges::any_of(available, [&](const VkExtensionProperties& p) {
            return std::strcmp(p.extensionName, names[i]) == 0;
        });
        if (offered) {
            enabled.push_back(names[i]); // owned by the provider DLL, which stays loaded
        } else {
            std::printf("Upscaler provider %s: instance extension %s is not offered\n",
                        provider->key, names[i]);
        }
    }
    provider->instance_extensions_enabled = enabled.size() == count;
    return enabled;
}

void EnableSelectedProviderDeviceExtensions(VkInstance instance, VkPhysicalDevice physical,
                                            const std::function<bool(std::string_view)>& enable) {
    UpscaleProvider* provider = Selected();
    if (!provider || !provider->api.required_device_extensions) {
        return;
    }
    u32 count = 0;
    const char* const* names = nullptr;
    char error[256]{};
    if (provider->api.required_device_extensions(instance, physical, &count, &names, error,
                                                 sizeof(error)) != ORDER_UPSCALE_OK) {
        std::printf("Upscaler provider %s: cannot list its device extensions (%s)\n",
                    provider->key, error);
        return;
    }
    bool all = true;
    for (u32 i = 0; i < count; ++i) {
        provider->device_extensions.emplace_back(names[i]);
        all = enable(names[i]) && all; // names stay valid: the provider DLL stays loaded
    }
    provider->device_extensions_enabled = all;
}

std::span<const UpscaleProvider> DetectUpscaleProviders(const Instance& instance) {
    static const bool checked = [&] {
        for (auto& provider : Providers()) {
            Check(provider, instance);
            if (provider.available) {
                std::printf("Upscaler provider %s: %s %s available\n", provider.key,
                            provider.name.c_str(), provider.version.c_str());
            } else {
                std::printf("Upscaler provider %s: unavailable, %s\n", provider.key,
                            provider.reason.c_str());
            }
        }
        std::fflush(stdout);
        return true;
    }();
    (void)checked;
    return Providers();
}

void ReportUpscalerFallback(int requested, std::span<const UpscaleProvider> providers) {
    const auto& settings = Ps4Settings::Get();
    const char* path = settings.fsr1.load() ? "FSR 1" : "Linear";
    if (requested == Ps4Settings::UpscalerOff) {
        std::printf("Upscaler: off; presenting with %s\n", path);
        return;
    }
    const char* key = Ps4Settings::UpscalerName(requested);
    const auto it = std::ranges::find_if(providers, [&](const UpscaleProvider& provider) {
        return std::string_view(provider.key) == key;
    });
    if (it != providers.end() && it->available) {
        // vk_order_resolve.cpp runs it in place of the game's temporal resolve, at native size.
        std::printf("Upscaler: %s requested; %s replaces the game's temporal resolve, presenting "
                    "with %s\n",
                    key, it->name.c_str(), path);
        return;
    }
    const std::string status = it == providers.end() ? "no provider is built for it" : it->reason;
    std::printf("Upscaler: %s requested (%s); the game's temporal resolve stays, presenting with "
                "%s\n",
                key, status.c_str(), path);
}

} // namespace Vulkan
