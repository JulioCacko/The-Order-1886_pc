// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include <limits>

#include <boost/icl/interval_set.hpp>

#include "common/types.h"

namespace Vulkan {

class MappedRangeSnapshot {
public:
    using RangeSet = boost::icl::interval_set<VAddr>;

    [[nodiscard]] bool IsCurrent(u64 owner, u64 generation) const noexcept {
        return owner == cached_owner && generation == cached_generation;
    }

    void Refresh(u64 owner, u64 generation, const RangeSet& ranges) {
        cached_ranges = ranges;
        cached_owner = owner;
        cached_generation = generation;
    }

    [[nodiscard]] bool Contains(VAddr address, u64 size) const {
        if (size == 0 ||
            static_cast<u64>(address) > std::numeric_limits<u64>::max() - size) {
            return false;
        }
        const auto range = RangeSet::interval_type::right_open(address, address + size);
        return boost::icl::contains(cached_ranges, range);
    }

private:
    RangeSet cached_ranges;
    u64 cached_owner = 0;
    u64 cached_generation = ~u64{0};
};

} // namespace Vulkan
