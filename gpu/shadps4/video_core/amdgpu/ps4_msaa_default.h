// SPDX-License-Identifier: GPL-2.0-or-later
// The Vulkan drivers where the game's multisampled images are created single-sampled unless
// ORDER1886_NO_MSAA says otherwise (ps4_msaa.h). Plain C, so tests and tools can include it.
//
// AMD's proprietary driver: the RX 6600 family reads a multisampled depth buffer wrong from a
// shader and the lighting shows black lines (DivinusX port #4, gow3_pc #65, where five RX
// 6600/6650 XT owners confirmed the fix). NVIDIA, RADV, AMDVLK, Mesa ANV and MoltenVK read it
// correctly as far as known and keep the game's multisampling: the native baseline.
#pragma once

#include <vulkan/vulkan_core.h>

static inline int order1886_no_msaa_default(VkDriverId driver) {
    return driver == VK_DRIVER_ID_AMD_PROPRIETARY;
}

/* "0" or "1" in ORDER1886_NO_MSAA wins; anything else (or unset) uses the driver default. */
static inline int order1886_no_msaa(VkDriverId driver, const char* env) {
    if (env && (env[0] == '0' || env[0] == '1') && env[1] == '\0')
        return env[0] == '1';
    return order1886_no_msaa_default(driver);
}
