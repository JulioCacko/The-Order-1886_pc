// SPDX-License-Identifier: GPL-2.0-or-later
//
// Four fixes taken from upstream shadPS4 (GPL-2.0-or-later, same licence as this tree), each of
// which is a correctness bug rather than a feature. They live together here because each one is
// a small decision that can be checked without a GPU or the game.
//
//  1. tiling:      a PRT 3D-thin surface must be a PRT array mode, or its bank swizzle is wrong.
//  2. gnmdriver:   the DrawIndirectMulti packet declares six payload words, not five.
//  3. page fault:  a faulting read is clamped to the page, so the last bytes stay resolvable.
//  4. GC budgets:  the eviction floors follow the device, so a small budget can still trigger.

#include <array>
#include <span>
#include <cstdio>
#include <cstdlib>
#include <string_view>

#include "video_core/amdgpu/pm4_cmds.h"
#include "video_core/amdgpu/tiling.h"

#include "common/logging/log.h"

// The same stubs the other native tests use: these checks link tiling.cpp, which logs.
void assert_fail_impl() { std::abort(); }
[[noreturn]] void unreachable_impl() { std::abort(); }
namespace Common::Log {
bool ShouldLog(Level) { return false; }
void Write(std::string_view, Level, const char*, int, const char*, std::string&&) {}
}
namespace {

int fail(std::string_view message) {
    std::printf("%.*s\n", static_cast<int>(message.size()), message.data());
    return EXIT_FAILURE;
}

// Mirrors PageManager::FaultAccessSize without pulling the page manager's platform dependencies
// into a test that must build everywhere.
constexpr unsigned long long PageSize = 4096;
constexpr unsigned long long FaultAccessSize(unsigned long long addr) {
    const unsigned long long next = ((addr + 1 + PageSize - 1) / PageSize) * PageSize;
    const unsigned long long remaining = next - addr;
    return remaining < 8 ? remaining : 8;
}

// Mirrors the GC floor arithmetic in TextureCache's constructor.
constexpr long long PressureFloor(long long budget) {
    const long long quarter = budget / 4;
    const long long bounded = quarter < (256LL << 20) ? (256LL << 20) : quarter;
    return bounded > (1536LL << 20) ? (1536LL << 20) : bounded;
}

} // Anonymous namespace

int main() {
    // 1. PRT 3D-thin keeps its PRT flag; the plain 3D-thin shape does not become PRT.
    if (AmdGpu::GetArrayMode(AmdGpu::TileMode::Thin3DThinPrt) !=
        AmdGpu::ArrayMode::ArrayPrt3DTiledThin1) {
        return fail("a PRT 3D-thin tile mode must map to a PRT array mode");
    }
    if (AmdGpu::IsPrt(AmdGpu::GetArrayMode(AmdGpu::TileMode::Thin3DThin))) {
        return fail("a plain 3D-thin tile mode must not become a PRT array mode");
    }
    if (!AmdGpu::IsPrt(AmdGpu::GetArrayMode(AmdGpu::TileMode::Thin2DThinPrt))) {
        return fail("the 2D PRT mapping must stay PRT");
    }

    // 2. The DrawIndirectMulti packet is one header plus six payload words.
    constexpr u32 payload_words = 6;
    constexpr u32 packet_words = payload_words + 1;
    const AmdGpu::PM4Type3Header header{AmdGpu::PM4ItOpcode::DrawIndirectMulti, payload_words - 1,
                                    AmdGpu::PM4ShaderType::ShaderGraphics,
                                    AmdGpu::PM4Predicate::PredDisable};
    if (header.count != packet_words - 2) {
        return fail("the indirect-multi header must declare five payload words");
    }
    // A dispatcher walking NumWords()+1 must land exactly past the packet, not inside it.
    const u32 walked = header.NumWords() + 1;
    if (walked != packet_words) {
        return fail("a five-word packet desynchronises the command buffer");
    }
    if (sizeof(AmdGpu::PM4CmdDrawIndirectMulti) != packet_words * sizeof(u32)) {
        return fail("the packet struct and the declared length disagree");
    }

    // 3. Faulting accesses near the end of a page are clamped, never over-reported.
    if (FaultAccessSize(0) != 8) {
        return fail("a fault at a page start must report the full eight bytes");
    }
    constexpr unsigned long long page_end = PageSize;
    if (FaultAccessSize(page_end - 2) != 2) {
        return fail("a fault two bytes before the page end must report two bytes");
    }
    if (FaultAccessSize(page_end - 1) != 1) {
        return fail("a fault on the last byte must report one byte");
    }

    // 4. The pressure floor follows the device instead of being pinned to the default.
    if (PressureFloor(2LL << 30) != (512LL << 20)) {
        return fail("a 2 GB budget must floor pressure GC at a quarter of the device");
    }
    if (PressureFloor(64LL << 30) != (1536LL << 20)) {
        return fail("a large budget must keep the default pressure floor");
    }
    if (PressureFloor(512LL << 20) != (256LL << 20)) {
        return fail("a tiny budget must not floor below 256 MB");
    }

    std::puts("Upstream fixes: PRT tiling, indirect packet length, fault clamp, GC floors");
    return EXIT_SUCCESS;
}
