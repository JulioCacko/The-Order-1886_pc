// Optional raw timing evidence. Existing files are preserved; collection is independent of UI.
#pragma once
#include <cstdint>
#include <cstdio>
#include <mutex>
#ifdef _WIN32
#include <filesystem>
#include <string_view>
#endif

namespace Ps4PerfStats {
class FrameTrace {
public:
    explicit FrameTrace(const char* path) {
        if (!path || !*path) return;
#ifdef _WIN32
        try {
            const std::filesystem::path filename{
                std::u8string_view{reinterpret_cast<const char8_t*>(path)}};
            file = _wfopen(filename.c_str(), L"wx");
        } catch (const std::exception&) {
            file = nullptr;
        }
#else
        file = std::fopen(path, "wx");
#endif
        if (!file) {
            std::fprintf(stderr, "Frame trace: cannot create new evidence file %s\n", path);
            return;
        }
        std::fprintf(file, "event,timestamp_ns,render_serial,buffer_address,loading\n");
        std::fflush(file);
    }
    ~FrameTrace() { if (file) std::fclose(file); }
    FrameTrace(const FrameTrace&) = delete;
    FrameTrace& operator=(const FrameTrace&) = delete;
    bool Enabled() const { return file != nullptr; }
    void Record(const char* event, uint64_t timestamp, uint64_t render_serial,
                uint64_t buffer_address, bool loading) {
        if (!file) return;
        std::scoped_lock lock{mutex};
        std::fprintf(file, "%s,%llu,%llu,%llu,%d\n", event,
                     static_cast<unsigned long long>(timestamp),
                     static_cast<unsigned long long>(render_serial),
                     static_cast<unsigned long long>(buffer_address), int(loading));
        if (timestamp - last_flush >= 1'000'000'000) {
            std::fflush(file);
            last_flush = timestamp;
        }
    }
private:
    FILE* file = nullptr;
    uint64_t last_flush = 0;
    std::mutex mutex;
};
} // namespace Ps4PerfStats
