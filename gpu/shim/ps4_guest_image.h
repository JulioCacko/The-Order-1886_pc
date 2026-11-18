// SPDX-License-Identifier: GPL-2.0-or-later
// Where the runtime loaded the game executable's image (ps4gpu_set_guest_image), so the in-game
// menu can change the engine's frame interval live. Image-relative addresses (RVAs) are the ones
// the timing recipes use (scripts/order1886_frame_rate.py).
#pragma once
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace Ps4GuestImage {

inline std::atomic<unsigned char*> base{nullptr};
inline std::atomic<size_t> size{0};

// `mov dword [rip+disp32], imm32` at RVA 0x4507be writes the vblank interval global at RVA
// 0x15c0d54 (2 = 30 FPS, 1 = 60 FPS, 0 = the engine's uncapped mode). The menu only writes the
// global when this instruction is there with one of those immediates (the launcher's 90 FPS and
// Unlocked recipes write 1 or 0), i.e. the 01.02 code the timing recipes were verified against.
inline constexpr size_t IntervalWriteRva = 0x4507be;
inline constexpr size_t IntervalGlobalRva = 0x15c0d54;
inline constexpr unsigned char IntervalWritePrefix[6] = {0xc7, 0x05, 0x8c, 0x05, 0x17, 0x01};

/// The interval global, or nullptr when the loaded image is not the verified executable.
inline volatile uint32_t* IntervalGlobal() {
    unsigned char* const image = base.load(std::memory_order_acquire);
    const size_t length = size.load(std::memory_order_acquire);
    if (!image || length < IntervalGlobalRva + 4 || length < IntervalWriteRva + 10) {
        return nullptr;
    }
    const unsigned char* instruction = image + IntervalWriteRva;
    uint32_t immediate = 0;
    std::memcpy(&immediate, instruction + 6, 4);
    if (std::memcmp(instruction, IntervalWritePrefix, 6) != 0 || immediate > 2) {
        return nullptr;
    }
    return reinterpret_cast<volatile uint32_t*>(image + IntervalGlobalRva);
}

} // namespace Ps4GuestImage
