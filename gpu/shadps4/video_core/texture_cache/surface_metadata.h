// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once

#include <cstdint>
#include <limits>
#include <map>
#include <mutex>
#include <optional>

namespace VideoCore {

class SurfaceMetadata {
public:
    enum class Type { CMask, FMask, HTile };

    void Register(std::uint64_t address, std::uint64_t owner, Type type,
                  std::uint32_t clear_mask = ~0u, std::uint32_t layers = 1,
                  bool stencil = false) {
        std::scoped_lock lock{mutex};
        const auto it = entries.find(address);
        if (it == entries.end() || it->second.owner != owner || it->second.type != type ||
            it->second.layers != layers || it->second.stencil != stencil) {
            WriteLocked(address, it != entries.end() && it->second.size ? it->second.size : 1);
            entries.insert_or_assign(address, Entry{owner, type, clear_mask, layers, stencil});
        }
    }

    void Erase(std::uint64_t address, std::uint64_t owner) {
        std::scoped_lock lock{mutex};
        const auto it = entries.find(address);
        if (it != entries.end() && it->second.owner == owner) entries.erase(it);
    }

    void Unmap(std::uint64_t address, std::uint64_t size) {
        if (!size) return;
        std::scoped_lock lock{mutex};
        for (auto it = entries.begin(); it != entries.end();) {
            const auto extent = it->second.size ? it->second.size : 1;
            if (address <= it->first ? it->first - address < size : address - it->first < extent)
                it = entries.erase(it);
            else ++it;
        }
    }

    std::optional<Type> TypeAt(std::uint64_t address) const {
        std::scoped_lock lock{mutex};
        const auto it = entries.find(address);
        return it == entries.end() ? std::nullopt : std::optional{it->second.type};
    }

    bool IsCleared(std::uint64_t address, std::uint32_t slice) const {
        if (slice >= 32) return false;
        std::scoped_lock lock{mutex};
        const auto it = entries.find(address);
        return it != entries.end() && (it->second.clear_mask & (1u << slice));
    }

    bool Clear(std::uint64_t address, std::uint64_t size) {
        if (!size || (address & 3) || (size & 3) ||
            size > std::numeric_limits<std::uint64_t>::max() - address) return false;
        std::scoped_lock lock{mutex};
        const auto it = entries.find(address);
        if (it == entries.end()) return false;
        WriteLocked(address, size);
        auto& entry = it->second;
        entry.clear_mask = ~0u;
        entry.size = size;
        entry.shader_written = false;
        return true;
    }

    bool Touch(std::uint64_t address, std::uint32_t slice, bool clear) {
        std::scoped_lock lock{mutex};
        const auto it = entries.find(address);
        if (it == entries.end()) return false;
        auto& entry = it->second;
        if (slice >= 32) { entry.shader_written = true; entry.clear_mask = 0; return false; }
        const auto previous = entry.clear_mask;
        if (clear) entry.clear_mask |= 1u << slice;
        else entry.clear_mask &= ~(1u << slice);
        return previous != entry.clear_mask;
    }

    void Write(std::uint64_t address, std::uint64_t size) {
        if (!size) return;
        std::scoped_lock lock{mutex};
        WriteLocked(address, size);
    }

    void Fill(std::uint64_t address, std::uint64_t size, std::uint32_t value) {
        if (!size) return;
        std::scoped_lock lock{mutex};
        WriteLocked(address, size);
        const auto it = entries.find(address);
        if (it == entries.end() || (it->second.type == Type::HTile && (value & 0xf))) return;
        auto& entry = it->second;
        entry.clear_mask = ~0u;
        entry.size = size <= std::numeric_limits<std::uint64_t>::max() - address ? size : 0;
        entry.shader_written = false;
    }

    std::optional<std::uint32_t> HtileWord(std::uint64_t address, std::uint64_t size) const {
        if (!size || (address & 3) || (size & 3)) return std::nullopt;
        std::scoped_lock lock{mutex};
        auto it = entries.upper_bound(address);
        if (it == entries.begin()) return std::nullopt;
        --it;
        const auto& entry = it->second;
        const auto offset = address - it->first;
        if (offset > entry.size || size > entry.size - offset) {
            return std::nullopt;
        }
        return UniformWord(entry);
    }

    std::optional<std::uint32_t> HtileExtent(std::uint64_t address) const {
        std::scoped_lock lock{mutex};
        const auto it = entries.find(address);
        if (it == entries.end() || !it->second.size ||
            it->second.size > std::numeric_limits<std::uint32_t>::max() ||
            (it->second.size & 3) || !UniformWord(it->second)) return std::nullopt;
        return static_cast<std::uint32_t>(it->second.size);
    }

private:
    struct Entry {
        std::uint64_t owner;
        Type type;
        std::uint32_t clear_mask, layers;
        bool stencil;
        std::uint64_t size{};
        bool shader_written{};
    };
    static std::optional<std::uint32_t> UniformWord(const Entry& entry) {
        if (entry.type != Type::HTile || entry.shader_written || !entry.layers ||
            entry.layers > 32) return std::nullopt;
        const std::uint32_t active = entry.layers == 32 ? ~0u : (1u << entry.layers) - 1;
        const auto cleared = entry.clear_mask & active;
        // shortcut: mixed slices use real bytes until the HTILE slice layout is verified.
        if (cleared && cleared != active) return std::nullopt;
        const std::uint32_t expanded = entry.stencil ? 0xfffff3ffu : 0xfffc000fu;
        return cleared ? expanded & ~0xfu : expanded;
    }

    void WriteLocked(std::uint64_t address, std::uint64_t size) {
        for (auto& [base, entry] : entries) {
            const auto extent = entry.size ? entry.size : 1;
            if (address <= base ? base - address < size : address - base < extent) {
                entry.shader_written = true;
                entry.clear_mask = 0;
            }
        }
    }
    mutable std::mutex mutex;
    std::map<std::uint64_t, Entry> entries;
};

} // namespace VideoCore
