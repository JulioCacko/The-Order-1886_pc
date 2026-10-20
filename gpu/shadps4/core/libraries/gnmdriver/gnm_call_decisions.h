// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once

// The decisions three GnmDriver entry points make, kept out of the guest-callable bodies so they
// can be checked without a GPU or a guest.
//
// All three were stubs in this tree: they returned ORBIS_OK while writing nothing into the buffer
// the guest handed them, which leaves guest garbage at that command-buffer position and lets the
// dispatcher read it as packet headers. The semantics below are taken from upstream shadPS4
// (GPL-2.0-or-later, same licence).

#include <cstdint>
#include <span>

#include "video_core/amdgpu/pm4_cmds.h"

namespace Gnm {

/// A compute wait-semaphore packet is exactly ten dwords: three NOPs, the MemSemaphore header and
/// its two payload dwords, then two more NOPs.
constexpr uint32_t ComputeWaitSemaphoreDwords = 0xa;

/// Writes the packet the guest asked for and returns the position after it. The caller has already
/// checked that the buffer is non-null and that the guest asked for `ComputeWaitSemaphoreDwords`.
inline uint32_t* WriteComputeWaitSemaphore(uint32_t* cmdbuf, uint64_t semaphore_address,
                                           uint32_t flags) {
    // A NOP with a data block of N carries a header plus N dwords, and its count field is N-1.
    auto* leading = reinterpret_cast<AmdGpu::PM4CmdNop*>(cmdbuf);
    leading->header = AmdGpu::PM4Type3Header{AmdGpu::PM4ItOpcode::Nop, 2}; // three data dwords
    for (u32 i = 0; i < 3; ++i) {
        leading->data_block[i] = 0u;
    }
    cmdbuf += 1 + 3;
    cmdbuf = AmdGpu::WriteHeader<AmdGpu::PM4ItOpcode::MemSemaphore>(cmdbuf, 2);
    cmdbuf[0] = static_cast<uint32_t>(semaphore_address);
    cmdbuf[1] = (flags == 1 ? 0x100000u : 0u) - 0x20000000u +
                static_cast<uint32_t>(semaphore_address >> 32);
    cmdbuf += 2;
    auto* trailing = reinterpret_cast<AmdGpu::PM4CmdNop*>(cmdbuf);
    trailing->header = AmdGpu::PM4Type3Header{AmdGpu::PM4ItOpcode::Nop, 1}; // two data dwords
    for (u32 i = 0; i < 2; ++i) {
        trailing->data_block[i] = 0u;
    }
    return cmdbuf + 1 + 2;
}

/// Sony's libSceGnmDriver validates both ring sizes before accepting them.
constexpr uint32_t MinGsRingSize = 0x400000;   // 4 MB
constexpr uint32_t MaxGsRingSize = 0x800000;   // 8 MB
constexpr uint32_t GsRingAlignment = 0x100000; // 1 MB
constexpr uint32_t GsRingInvalidArgument = 0x08000000;

constexpr bool ValidGsRingSize(uint32_t size) {
    return size >= MinGsRingSize && size <= MaxGsRingSize && (size & (GsRingAlignment - 1)) == 0;
}

/// Zero when both sizes are acceptable, the guest error code otherwise.
constexpr uint32_t ValidateGsRingSizes(uint32_t esgs_ring_size, uint32_t gsvs_ring_size) {
    return ValidGsRingSize(esgs_ring_size) && ValidGsRingSize(gsvs_ring_size)
               ? 0
               : GsRingInvalidArgument;
}

/// The guest inspects the first dword of the report buffer for this sentinel.
constexpr uint32_t MipStatsReportSentinel = 0x40;
constexpr uint32_t MipStatsMinSize = 0x1040;
constexpr uint32_t MipStatsSizeGranularity = 0x7ff;
constexpr uint32_t MipStatsSizeRemainder = 0x40;
constexpr uint32_t MipStatsInvalidBuffer = 0x80000001;
constexpr uint32_t MipStatsInvalidSize = 0x80000002;

/// Zero when the buffer can hold a report, the guest error code otherwise.
inline uint32_t ValidateMipStatsReport(const void* output_buffer, uint32_t size_in_bytes) {
    if (output_buffer == nullptr ||
        (reinterpret_cast<uintptr_t>(output_buffer) & 0xffffff000000003fULL) != 0) {
        return MipStatsInvalidBuffer;
    }
    if (size_in_bytes < MipStatsMinSize ||
        (size_in_bytes & MipStatsSizeGranularity) != MipStatsSizeRemainder) {
        return MipStatsInvalidSize;
    }
    return 0;
}

} // namespace Gnm
