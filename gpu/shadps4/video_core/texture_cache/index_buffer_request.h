// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once

// How much of the index buffer to obtain for a draw.
//
// Taken from upstream shadPS4. An indexed draw takes its count from a register, but an indexed
// *indirect* draw takes it from the indirect buffer and is only bounded by `max_index_size`; and
// either way the request must be clamped to mapped memory, or the buffer cache is asked for a
// range that does not exist. The decision lives here so it can be checked without a device.

#include <algorithm>
#include <cstdint>

namespace VideoCore {

struct IndexBufferRequest {
    /// Bytes to obtain from the buffer cache. Zero means the range is not mapped at all.
    uint32_t size;
    /// Indices the draw will actually read, once the request has been clamped.
    uint32_t indices;
};

constexpr IndexBufferRequest ResolveIndexRequest(uint32_t num_indices, uint32_t max_index_size,
                                                  bool is_indirect, uint32_t index_size,
                                                  uint64_t mapped_size) {
    const uint32_t wanted =
        is_indirect ? max_index_size : std::min(num_indices, max_index_size);
    if (index_size == 0) {
        return {0, 0};
    }
    const uint64_t requested = static_cast<uint64_t>(wanted) * index_size;
    const uint64_t available = std::min(requested, mapped_size);
    // A partial index is useless: the binding must end on an index boundary.
    const uint64_t aligned = available - (available % index_size);
    return {static_cast<uint32_t>(aligned), static_cast<uint32_t>(aligned / index_size)};
}

} // namespace VideoCore
