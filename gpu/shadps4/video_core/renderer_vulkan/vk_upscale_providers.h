// SPDX-License-Identifier: GPL-2.0-or-later
// Temporal upscaler providers (shim/order1886_upscale.h): which ones this runtime and device
// can use, and why not (#7). The Order's integration of a provider is vk_order_resolve.cpp.
#pragma once

#include <functional>
#include <span>
#include <string>
#include <string_view>
#include <vector>
#include <vulkan/vulkan.h>
#include "order1886_upscale.h"

namespace Vulkan {

class Instance;

struct UpscaleProvider {
    const char* key;     ///< settings name: fsr3, dlss
    const char* library; ///< DLL next to the runtime
    const char* symbol;  ///< exported OrderUpscaleGetApi
    bool loaded = false;
    bool available = false;
    std::string name, version;
    std::string reason; ///< why it is unavailable; empty when available
    OrderUpscaleProviderApi api{};
    /// Extensions it asked for and whether every one was enabled. Only the provider the launcher
    /// selected gets its extensions: they change the instance and device for every other path.
    std::vector<std::string> instance_extensions, device_extensions;
    bool instance_extensions_enabled = false, device_extensions_enabled = false;
};

/// Before the Vulkan instance exists: the instance extensions the selected provider needs and
/// that `available` offers. Loads that provider's DLL; an empty list when none is selected.
std::vector<const char*> SelectedProviderInstanceExtensions(
    std::span<const VkExtensionProperties> available);

/// Before the device exists: passes each device extension the selected provider needs to
/// `enable`, which returns whether the device offers it.
void EnableSelectedProviderDeviceExtensions(VkInstance instance, VkPhysicalDevice physical,
                                            const std::function<bool(std::string_view)>& enable);

/// Loads and checks every known provider once, logs one line each, and returns them.
std::span<const UpscaleProvider> DetectUpscaleProviders(const Instance& instance);

/// Logs which presentation path runs when an upscaler was requested (`requested`, a
/// Ps4Settings::Upscaler): the provider replacing the game's temporal resolve, or why none can.
void ReportUpscalerFallback(int requested, std::span<const UpscaleProvider> providers);

} // namespace Vulkan
