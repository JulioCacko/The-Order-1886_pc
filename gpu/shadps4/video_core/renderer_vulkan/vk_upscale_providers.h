// SPDX-License-Identifier: GPL-2.0-or-later
// Temporal upscaler providers (shim/order1886_upscale.h): which ones this runtime and device
// can use, and why not (#7). The Order's integration of a provider is #10-#13.
#pragma once

#include <span>
#include <string>
#include "order1886_upscale.h"

namespace Vulkan {

class Instance;

struct UpscaleProvider {
    const char* key;     ///< settings name: fsr3, dlss
    const char* library; ///< DLL next to the runtime
    const char* symbol;  ///< exported OrderUpscaleGetApi
    bool available = false;
    std::string name, version;
    std::string reason; ///< why it is unavailable; empty when available
    OrderUpscaleProviderApi api{};
};

/// Loads and checks every known provider once, logs one line each, and returns them.
std::span<const UpscaleProvider> DetectUpscaleProviders(const Instance& instance);

/// Logs which presentation path runs when an upscaler was requested (`requested`, a
/// Ps4Settings::Upscaler) and the reason it cannot run yet.
void ReportUpscalerFallback(int requested, std::span<const UpscaleProvider> providers);

} // namespace Vulkan
