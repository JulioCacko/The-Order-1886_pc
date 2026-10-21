// SPDX-License-Identifier: GPL-2.0-or-later
// See vk_upscale_providers.h.

#include <algorithm>
#include <array>
#include <cstdio>
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

/// Device extensions this runtime does not enable today are named in the reason, with whether
/// the GPU offers them, so the gap between "loadable" and "usable" stays visible.
std::string MissingDeviceExtensions(const UpscaleProvider& provider, const Instance& instance) {
    if (!provider.api.required_device_extensions) {
        return {};
    }
    u32 count = 0;
    const char* const* names = nullptr;
    char error[256]{};
    if (provider.api.required_device_extensions(instance.GetInstance(), instance.GetPhysicalDevice(),
                                                &count, &names, error, sizeof(error)) !=
        ORDER_UPSCALE_OK) {
        return std::string("cannot list its device extensions: ") + error;
    }
    std::string missing;
    const auto available = instance.GetAvailableExtensions();
    for (u32 i = 0; i < count; ++i) {
        const bool offered = std::ranges::find(available, std::string(names[i])) != available.end();
        missing += (missing.empty() ? "" : ", ") + std::string(names[i]) +
                   (offered ? " (offered by the GPU, not enabled by the runtime)" : " (not offered by the GPU)");
    }
    return missing.empty() ? std::string{} : "needs device extensions " + missing;
}

void Check(UpscaleProvider& provider, const Instance& instance) {
#ifdef _WIN32
    const auto path = RuntimeDirectory() / provider.library;
    if (!std::filesystem::exists(path)) {
        provider.reason = std::string(provider.library) + " is not next to the runtime";
        return;
    }
    HMODULE module = LoadLibraryExW(path.c_str(), nullptr,
                                    LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    if (!module) {
        provider.reason = std::string(provider.library) + " failed to load (error " +
                          std::to_string(GetLastError()) + ")";
        return;
    }
    const auto get_api = reinterpret_cast<OrderUpscaleGetApi>(
        reinterpret_cast<void*>(GetProcAddress(module, provider.symbol)));
    if (!get_api) {
        provider.reason = std::string(provider.library) + " does not export " + provider.symbol;
        return;
    }
    if (get_api(ORDER1886_UPSCALE_ABI, &provider.api) != ORDER_UPSCALE_OK ||
        provider.api.abi_version != ORDER1886_UPSCALE_ABI) {
        provider.reason = "provider does not implement ABI " + std::to_string(ORDER1886_UPSCALE_ABI);
        return;
    }
    provider.name = provider.api.name ? provider.api.name : provider.key;
    provider.version = provider.api.version ? provider.api.version : "";
    if (provider.api.required_instance_extensions) {
        u32 count = 0;
        const char* const* names = nullptr;
        char error[256]{};
        if (provider.api.required_instance_extensions(&count, &names, error, sizeof(error)) !=
                ORDER_UPSCALE_OK ||
            count != 0) {
            provider.reason = "needs instance extensions the runtime does not enable";
            return;
        }
    }
    provider.reason = MissingDeviceExtensions(provider, instance);
    if (provider.reason.empty() && !instance.IsStorageImageWriteWithoutFormatEnabled()) {
        provider.reason = "shaderStorageImageWriteWithoutFormat is not enabled on this device";
    }
    provider.available = provider.reason.empty();
#else
    provider.reason = "providers are Windows DLLs";
#endif
}

} // namespace

std::span<const UpscaleProvider> DetectUpscaleProviders(const Instance& instance) {
    static std::vector<UpscaleProvider> providers = [&] {
        std::vector<UpscaleProvider> list{
            {.key = "fsr3", .library = "order1886_fsr3.dll", .symbol = "order1886_fsr_get_api"},
            {.key = "dlss", .library = "order1886_dlss.dll", .symbol = "order1886_dlss_get_api"},
        };
        for (auto& provider : list) {
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
        return list;
    }();
    return providers;
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
    const std::string status = it == providers.end() ? "no provider is built for it"
                               : it->available       ? it->name + " loads on this device"
                                                     : it->reason;
    // The Order's temporal resolve is not routed to a provider yet (#10-#13), so the explicit
    // fallback is the presentation path, whatever the provider status.
    std::printf("Upscaler: %s requested (%s); not integrated with The Order yet, presenting with %s\n",
                key, status.c_str(), path);
}

} // namespace Vulkan
