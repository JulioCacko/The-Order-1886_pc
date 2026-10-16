// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <atomic>
namespace AmdGpu {
// Preserve the guest's multisampling semantics in the native PS4 baseline.
inline std::atomic<bool> no_msaa{false};
inline bool NoMsaa() { return false; }
} // namespace AmdGpu
