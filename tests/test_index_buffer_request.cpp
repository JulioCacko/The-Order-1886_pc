// SPDX-License-Identifier: GPL-2.0-or-later
//
// An indexed indirect draw takes its index count from the indirect buffer, not from the register
// that this tree used unconditionally: the obtained range could be smaller than the indices the
// draw reads, and the request was never clamped to mapped memory. Upstream shadPS4 sizes and
// clamps it; this pins the decision without needing a device.

#include <cstdio>
#include <cstdlib>
#include <string_view>

#include "video_core/texture_cache/index_buffer_request.h"

namespace {

int fail(std::string_view message) {
    std::printf("%.*s\n", static_cast<int>(message.size()), message.data());
    return EXIT_FAILURE;
}

using VideoCore::ResolveIndexRequest;

constexpr uint32_t U16 = 2;
constexpr uint32_t U32 = 4;
constexpr uint64_t Enough = 1ull << 20;

} // Anonymous namespace

int main() {
    // A direct draw reads at most what the register claims, and never more than max_index_size.
    auto direct = ResolveIndexRequest(300, 1000, false, U32, Enough);
    if (direct.indices != 300 || direct.size != 300 * U32) {
        return fail("a direct draw must request its own index count");
    }
    direct = ResolveIndexRequest(5000, 1000, false, U32, Enough);
    if (direct.indices != 1000 || direct.size != 1000 * U32) {
        return fail("a direct draw must not exceed max_index_size");
    }

    // An indirect draw is bounded by max_index_size, not by the stale register.
    auto indirect = ResolveIndexRequest(1, 4096, true, U32, Enough);
    if (indirect.indices != 4096 || indirect.size != 4096 * U32) {
        return fail("an indirect draw must be sized from max_index_size");
    }

    // Both are clamped to what is actually mapped, aligned down to a whole index.
    auto clamped = ResolveIndexRequest(1000, 1000, false, U32, 6);
    if (clamped.size != 4 || clamped.indices != 1) {
        return fail("a clamped request must end on an index boundary");
    }
    clamped = ResolveIndexRequest(1000, 1000, false, U16, 3);
    if (clamped.size != 2 || clamped.indices != 1) {
        return fail("a clamped 16-bit request must end on an index boundary");
    }

    // Nothing mapped means nothing to obtain, and the caller must handle that explicitly.
    const auto unmapped = ResolveIndexRequest(64, 64, false, U32, 0);
    if (unmapped.size != 0 || unmapped.indices != 0) {
        return fail("an unmapped range must request nothing");
    }

    // A degenerate index size cannot produce a request.
    if (ResolveIndexRequest(64, 64, false, 0, Enough).size != 0) {
        return fail("a zero index size must request nothing");
    }

    std::puts("Index buffer request: indirect sizing and mapped-memory clamp");
    return EXIT_SUCCESS;
}
