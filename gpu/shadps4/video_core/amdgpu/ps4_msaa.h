// SPDX-License-Identifier: GPL-2.0-or-later
// Guest multisampled images created and sampled as single-sampled ones, on drivers that cannot
// read a compressed multisampled depth buffer from a shader.
//
// The native PS4 baseline keeps the guest's sample counts, and every driver known to read the
// game's multisampled depth correctly keeps them. AMD's proprietary driver does not on RDNA2
// (RX 6600 family): a shader fetch of a multisampled depth buffer (texelFetch on a
// sampler2DMS) returns zero in the lower half of many 8x8 pixel tiles, the ones with little
// depth variation, which looks like compressed depth read without being expanded. Lighting
// that uses that depth then shows black lines 4 pixels tall every 8 render rows, only where
// light falls (issue #4 of the DivinusX port; gow3_pc #65 found and fixed the same fault on
// the same emulation core). Sampling in the General layout does not help, so on that driver
// the images lose their extra samples instead: the depth test and the shaders then use the
// same single-sampled buffer. Guest sizes and addresses still use the real sample count
// (GuestNumSamples).
//
// The default per driver is ps4_msaa_default.h; ORDER1886_NO_MSAA=0 or 1 decides otherwise
// (vk_instance.cpp).
#pragma once
#include <atomic>
namespace AmdGpu {
inline std::atomic<bool> no_msaa{false};
inline bool NoMsaa() {
    return no_msaa.load(std::memory_order_relaxed);
}
} // namespace AmdGpu
