// SPDX-License-Identifier: GPL-2.0-or-later
// numbers for the performance overlay (ps4_overlay.cpp). A thread started once samples
// CPU, RAM, GPU use (Windows counters) and VRAM (VK_EXT_memory_budget) twice a second;
// a value that cannot be measured stays negative and shows as "n/a".

#pragma once

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <string>

namespace Vulkan {
class Instance;
}

namespace Ps4PerfStats {

/// Overlay items (Ps4Settings::Values::overlay_items).
enum Item : unsigned {
    Fps = 1u << 0,
    FrameTime = 1u << 1,
    Upscaler = 1u << 2,
    Gpu = 1u << 3,
    Cpu = 1u << 4,
    Ram = 1u << 5,
    Vram = 1u << 6,
    AllItems = (1u << 7) - 1,
};
inline constexpr unsigned DefaultItems = Fps | FrameTime | Cpu | Ram;

struct PresentationMetrics {
    float fps = -1.0f, interval_ms = -1.0f;
    bool loading = false;
    bool stale = false;
};

// Successful host presentation intervals, including stalls. UI visibility does not
// affect collection, and loading-screen presents do not contaminate game presents.
class PresentationCounter {
public:
    void Present(uint64_t now_ns, bool loading) {
        if (!seen || loading != metrics.loading || now_ns <= last_ns) {
            seen = true;
            last_ns = now_ns;
            elapsed_ns = intervals = 0;
            metrics = {.loading = loading};
            return;
        }
        elapsed_ns += now_ns - last_ns;
        last_ns = now_ns;
        ++intervals;
        if (elapsed_ns >= 500'000'000) {
            metrics.fps = float(double(intervals) * 1'000'000'000.0 / double(elapsed_ns));
            metrics.interval_ms = float(double(elapsed_ns) / (double(intervals) * 1'000'000.0));
            elapsed_ns = intervals = 0;
        }
    }

    PresentationMetrics Latest() const { return metrics; }
    // Query age without inserting synthetic frames. Before the first event stays n/a.
    PresentationMetrics Latest(uint64_t now_ns) const {
        if (seen && now_ns >= last_ns && now_ns - last_ns >= 1'000'000'000) {
            return {.fps = 0.0f, .interval_ms = -1.0f, .loading = metrics.loading, .stale = true};
        }
        return metrics;
    }

private:
    bool seen = false;
    uint64_t last_ns{}, elapsed_ns{}, intervals{};
    PresentationMetrics metrics;
};

struct Sample {
    float fps = -1.0f, frame_ms = -1.0f;
    float game_fps = -1.0f, game_frame_ms = -1.0f;
    bool game_stale = false;
    std::string upscaler;
    std::string gpu_name;
    float gpu_percent = -1.0f, cpu_percent = -1.0f;
    double ram_used_gb = -1.0, ram_total_gb = -1.0, vram_used_gb = -1.0, vram_total_gb = -1.0;
};

/// Process CPU time over wall time on every core, 0 to 100; -1 without a wall interval.
inline float CpuPercent(uint64_t process_delta, uint64_t wall_delta, unsigned cores) {
    if (!wall_delta || !cores) {
        return -1.0f;
    }
    return std::clamp(float(double(process_delta) * 100.0 / (double(wall_delta) * cores)), 0.0f, 100.0f);
}

/// The overlay text for the items in `mask`: one line each, or one line when `row`.
inline std::string Format(const Sample& s, unsigned mask, bool row) {
    std::string out;
    char part[160];
    const auto add = [&] {
        if (!out.empty()) {
            out += row ? "   " : "\n";
        }
        out += part;
    };
    const auto pair = [](char* to, size_t size, const char* label, double used, double total) {
        if (used < 0.0) {
            std::snprintf(to, size, "%s n/a", label);
        } else if (total < 0.0) {
            std::snprintf(to, size, "%s %.1f GB", label, used);
        } else {
            std::snprintf(to, size, "%s %.1f / %.1f GB", label, used, total);
        }
    };
    if (mask & Fps) {
        if (s.game_fps < 0.0f) std::snprintf(part, sizeof(part), "Game output FPS n/a");
        else std::snprintf(part, sizeof(part), "Game output %.1f FPS%s", s.game_fps,
                           s.game_stale ? " (stale)" : "");
        add();
        if (s.fps < 0.0f) std::snprintf(part, sizeof(part), "Presentation FPS n/a");
        else std::snprintf(part, sizeof(part), "Presentation %.1f FPS", s.fps);
        add();
    }
    if (mask & FrameTime) {
        if (s.game_stale) std::snprintf(part, sizeof(part), "Guest flip interval stale");
        else if (s.game_frame_ms < 0.0f) std::snprintf(part, sizeof(part), "Guest flip interval n/a");
        else std::snprintf(part, sizeof(part), "Guest flip interval %.1f ms", s.game_frame_ms);
        add();
        if (s.frame_ms < 0.0f) std::snprintf(part, sizeof(part), "Present interval n/a");
        else std::snprintf(part, sizeof(part), "Present interval %.1f ms", s.frame_ms);
        add();
    }
    if (mask & Upscaler) {
        std::snprintf(part, sizeof(part), "%s", s.upscaler.empty() ? "Native" : s.upscaler.c_str());
        add();
    }
    if (mask & Gpu) {
        const char* name = s.gpu_name.empty() ? "GPU" : s.gpu_name.c_str();
        if (s.gpu_percent < 0.0f) {
            std::snprintf(part, sizeof(part), "%s n/a", name);
        } else {
            std::snprintf(part, sizeof(part), "%s %.0f%%", name, s.gpu_percent);
        }
        add();
    }
    if (mask & Cpu) {
        if (s.cpu_percent < 0.0f) {
            std::snprintf(part, sizeof(part), "Process CPU n/a");
        } else {
            std::snprintf(part, sizeof(part), "Process CPU %.0f%%", s.cpu_percent);
        }
        add();
    }
    if (mask & Ram) {
        if (s.ram_used_gb < 0.0) std::snprintf(part, sizeof(part), "Process RAM n/a");
        else std::snprintf(part, sizeof(part), "Process RAM %.1f GiB", s.ram_used_gb);
        add();
    }
    if (mask & Vram) {
        pair(part, sizeof(part), "VRAM", s.vram_used_gb, s.vram_total_gb);
        add();
    }
    return out;
}

/// Starts the sampling thread the first time; later calls do nothing.
void Start(const Vulkan::Instance& instance, unsigned items = DefaultItems);
/// Completed guest flips, independently of overlay visibility or UI-only host presentations.
void OnGuestFlip(uint64_t render_serial = 0, uint64_t buffer_address = 0, bool blank = false);
/// Successful host presents, including UI-only loading frames, in the optional raw trace.
void OnHostPresented(uint64_t timestamp_ns, bool loading);
/// Latest process and guest-output values (caller fills host presentation and upscaler).
Sample Latest();

} // namespace Ps4PerfStats
