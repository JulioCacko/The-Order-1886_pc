// SPDX-License-Identifier: GPL-2.0-or-later
#include "ps4_perf_stats.h"

#include <chrono>
#include <atomic>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>
#include "video_core/renderer_vulkan/vk_instance.h"

#ifdef _WIN32
#include <windows.h>
#include <pdh.h>
#include <pdhmsg.h>
#include <psapi.h>
#endif

namespace Ps4PerfStats {

namespace {

std::mutex mutex;
Sample latest;
PresentationCounter guest_output;
std::once_flag started;
std::atomic<unsigned> requested_items{DefaultItems};

#ifdef _WIN32
uint64_t Ticks(const FILETIME& time) {
    return (uint64_t(time.dwHighDateTime) << 32) | time.dwLowDateTime;
}

// This process's use of the GPU's 3D engines, as Task Manager shows it ("GPU Engine" counters,
// any vendor). Negative until the second sample or without the counters.
class GpuUsage {
public:
    GpuUsage() {
        if (PdhOpenQueryW(nullptr, 0, &query) != ERROR_SUCCESS) {
            query = nullptr;
            return;
        }
        if (PdhAddEnglishCounterW(query, L"\\GPU Engine(*)\\Utilization Percentage", 0, &counter) !=
            ERROR_SUCCESS) {
            PdhCloseQuery(query);
            query = nullptr;
            return;
        }
        PdhCollectQueryData(query);
        pid = L"pid_" + std::to_wstring(GetCurrentProcessId()) + L"_";
    }

    float Percent() {
        if (!query || PdhCollectQueryData(query) != ERROR_SUCCESS) {
            return -1.0f;
        }
        DWORD size = 0, count = 0;
        if (PdhGetFormattedCounterArrayW(counter, PDH_FMT_DOUBLE | PDH_FMT_NOCAP100, &size, &count,
                                         nullptr) != PDH_MORE_DATA) {
            return -1.0f;
        }
        buffer.resize(size);
        auto* items = reinterpret_cast<PDH_FMT_COUNTERVALUE_ITEM_W*>(buffer.data());
        if (PdhGetFormattedCounterArrayW(counter, PDH_FMT_DOUBLE | PDH_FMT_NOCAP100, &size, &count,
                                         items) != ERROR_SUCCESS) {
            return -1.0f;
        }
        double total = 0.0;
        for (DWORD i = 0; i < count; ++i) {
            const wchar_t* name = items[i].szName;
            if (items[i].FmtValue.CStatus == PDH_CSTATUS_VALID_DATA && wcsstr(name, pid.c_str()) &&
                wcsstr(name, L"engtype_3D")) {
                total += items[i].FmtValue.doubleValue;
            }
        }
        return std::clamp(float(total), 0.0f, 100.0f);
    }

private:
    PDH_HQUERY query = nullptr;
    PDH_HCOUNTER counter = nullptr;
    std::wstring pid;
    std::vector<unsigned char> buffer;
};

void Run(const Vulkan::Instance* instance) {
    std::unique_ptr<GpuUsage> gpu;
    FILETIME created, ended, kernel, user;
    uint64_t last_process = 0, last_wall = 0;
    const unsigned cores = std::max(1u, std::thread::hardware_concurrency());
    constexpr double GiB = 1024.0 * 1024.0 * 1024.0;
    while (true) {
        Sample s;
        const unsigned items = requested_items.load(std::memory_order_relaxed);
        if (items & (Gpu | Vram)) s.gpu_name = std::string(instance->GetModelName());
        if (GetProcessTimes(GetCurrentProcess(), &created, &ended, &kernel, &user)) {
            const uint64_t process = Ticks(kernel) + Ticks(user);
            const uint64_t wall = uint64_t(std::chrono::duration_cast<std::chrono::nanoseconds>(
                std::chrono::steady_clock::now().time_since_epoch()).count()) / 100;
            if (last_wall && wall > last_wall && process >= last_process) {
                s.cpu_percent = CpuPercent(process - last_process, wall - last_wall, cores);
            }
            last_process = process;
            last_wall = wall;
        }
        PROCESS_MEMORY_COUNTERS memory{};
        if (K32GetProcessMemoryInfo(GetCurrentProcess(), &memory, sizeof(memory))) {
            s.ram_used_gb = double(memory.WorkingSetSize) / GiB;
        }
        MEMORYSTATUSEX system{.dwLength = sizeof(MEMORYSTATUSEX)};
        if (GlobalMemoryStatusEx(&system)) {
            s.ram_total_gb = double(system.ullTotalPhys) / GiB;
        }
        if ((items & Vram) && instance->CanReportMemoryUsage()) {
            s.vram_used_gb = double(instance->GetDeviceMemoryUsage()) / GiB;
            s.vram_total_gb = double(instance->GetDeviceMemoryBudgetNow()) / GiB;
        }
        if (items & Gpu) {
            if (!gpu) gpu = std::make_unique<GpuUsage>();
            s.gpu_percent = gpu->Percent();
        }
        {
            std::scoped_lock lock{mutex};
            latest = std::move(s);
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }
}
#else
void Run(const Vulkan::Instance* instance) {
    while (true) {
        Sample s;
        s.gpu_name = std::string(instance->GetModelName());
        {
            std::scoped_lock lock{mutex};
            latest = std::move(s);
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }
}
#endif

} // namespace

void Start(const Vulkan::Instance& instance, unsigned items) {
    requested_items.store(items, std::memory_order_relaxed);
    // ponytail: never joined; a thread that ended while the game ran crashed in ntdll
    // (vk_pipeline_serialization.cpp, StopWarmUp). It sleeps between samples.
    std::call_once(started, [&] { std::thread(Run, &instance).detach(); });
}

void OnGuestFlip() {
    const auto now_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
                            std::chrono::steady_clock::now().time_since_epoch()).count();
    std::scoped_lock lock{mutex};
    guest_output.Present(uint64_t(now_ns), false);
}

Sample Latest() {
    std::scoped_lock lock{mutex};
    auto sample = latest;
    const auto now_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
                            std::chrono::steady_clock::now().time_since_epoch()).count();
    const auto timing = guest_output.Latest(uint64_t(now_ns));
    sample.game_fps = timing.fps;
    sample.game_frame_ms = timing.interval_ms;
    sample.game_stale = timing.stale;
    return sample;
}

} // namespace Ps4PerfStats
