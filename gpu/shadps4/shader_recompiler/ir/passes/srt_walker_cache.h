// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include <algorithm>
#include <atomic>
#include <cstddef>
#include <functional>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

#include "common/types.h"

namespace Shader {

// Generated SRT walkers live in a process-wide executable arena. The caller
// serializes Find/Store with the arena lock; NotePatch is safe from the signal
// handler and invalidates all cached addresses after one walker is rewritten.
template <typename Hasher = std::hash<std::string_view>>
class SrtWalkerCache {
public:
    explicit SrtWalkerCache(Hasher hasher = {}) : hasher{std::move(hasher)} {}

    [[nodiscard]] const u8* Find(const u8* code, size_t size) {
        SynchronizeGeneration();
        if (!code || size == 0) {
            return nullptr;
        }
        const std::string_view bytes{reinterpret_cast<const char*>(code), size};
        const auto [first, last] = entries.equal_range(hasher(bytes));
        for (auto it = first; it != last; ++it) {
            const auto& entry = it->second;
            if (entry.bytes.size() != size ||
                !std::equal(entry.bytes.begin(), entry.bytes.end(), code)) {
                continue;
            }
            if (patched_generation.load(std::memory_order_acquire) != cache_generation) {
                return nullptr;
            }
            return entry.code;
        }
        return nullptr;
    }

    bool Store(const u8* code, size_t size) {
        SynchronizeGeneration();
        if (!code || size == 0 || Find(code, size)) {
            return false;
        }
        const std::string_view bytes{reinterpret_cast<const char*>(code), size};
        entries.emplace(hasher(bytes), Entry{code, std::vector<u8>(code, code + size)});
        return true;
    }

    // Called before modifying executable bytes, so concurrent lookups reject
    // an entry that may be changing and later lookups discard the old cache.
    void NotePatch() noexcept {
        patched_generation.fetch_add(1, std::memory_order_release);
    }

private:
    struct Entry {
        const u8* code;
        std::vector<u8> bytes;
    };

    void SynchronizeGeneration() {
        const u64 generation = patched_generation.load(std::memory_order_acquire);
        if (generation != cache_generation) {
            entries.clear();
            cache_generation = generation;
        }
    }

    Hasher hasher;
    std::unordered_multimap<size_t, Entry> entries;
    std::atomic<u64> patched_generation{0};
    u64 cache_generation = 0;
};

} // namespace Shader
