// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <cstdint>

namespace Vulkan {
// Adapted from theorder1886-port 944c0ad: Intel drivers can render characters as
// black silhouettes with VK_EXT_vertex_input_dynamic_state. Keep the static path
// there unless the caller explicitly overrides it for driver diagnosis.
constexpr bool UseVertexInputDynamicState(std::uint32_t vendor, const char* override_value) {
    if (override_value && *override_value == '0') return false;
    if (override_value && *override_value == '1') return true;
    return vendor != 0x8086;
}
} // namespace Vulkan
