// Performance overlay text and settings (ps4_perf_stats.h, ps4_settings.cpp).
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <string>
#include <cmath>
#include "ps4_perf_stats.h"
#include "ps4_settings.h"

namespace P = Ps4PerfStats;

static std::string Read(const char* path) {
    std::ifstream in(path);
    std::stringstream s;
    s << in.rdbuf();
    return s.str();
}

int main() {
    P::PresentationCounter timing;
    assert(timing.Latest().fps < 0.0f);
    timing.Present(0, false);
    for (uint64_t i=1; i<=10; ++i) timing.Present(i*50'000'000, false);
    assert(std::abs(timing.Latest().fps-20.0f) < 0.001f);
    assert(std::abs(timing.Latest().interval_ms-50.0f) < 0.001f);
    // No overlay rendering is needed to collect presents. Long stalls remain in the rate.
    timing.Present(2'000'000'000, false);
    assert(std::abs(timing.Latest().fps-(2.0f/3.0f)) < 0.001f);
    assert(std::abs(timing.Latest().interval_ms-1500.0f) < 0.001f);
    timing.Present(3'000'000'000, true);
    assert(timing.Latest().fps < 0.0f && timing.Latest().loading);
    timing.Present(3'500'000'000, true);
    assert(timing.Latest().fps == 2.0f && timing.Latest().interval_ms == 500.0f);
    timing.Present(4'000'000'000, false);
    assert(timing.Latest().fps < 0.0f && !timing.Latest().loading);
    timing.Present(3'000'000'000, false); // clock discontinuity cannot underflow
    assert(timing.Latest().fps < 0.0f);
    timing.Present(3'500'000'000, false);
    assert(timing.Latest().fps == 2.0f);
    assert(P::CpuPercent(50, 100, 1) == 50.0f);
    assert(P::CpuPercent(400, 100, 8) == 50.0f);
    assert(P::CpuPercent(5000, 100, 4) == 100.0f);
    assert(P::CpuPercent(10, 0, 4) < 0.0f && P::CpuPercent(10, 100, 0) < 0.0f);

    P::Sample s;
    s.fps = 238.4f;
    s.frame_ms = 4.19f;
    s.upscaler = "FSR 3.1";
    s.gpu_name = "RTX 4070";
    s.gpu_percent = 87.2f;
    s.cpu_percent = 34.0f;
    s.ram_used_gb = 6.12;
    s.ram_total_gb = 31.9;
    s.vram_used_gb = 5.4;
    s.vram_total_gb = 12.0;
    assert(P::Format(s, P::DefaultItems, true) ==
           "Presentation 238.4 FPS   Present interval 4.2 ms   Process CPU 34%   Process RAM 6.1 GiB");
    assert(P::Format(s, P::AllItems, false) ==
           "Presentation 238.4 FPS\nPresent interval 4.2 ms\nFSR 3.1\nRTX 4070 87%\nProcess CPU 34%\nProcess RAM 6.1 GiB\nVRAM 5.4 / 12.0 GB");
    assert(P::Format(s, P::Cpu | P::Vram, true) == "Process CPU 34%   VRAM 5.4 / 12.0 GB");
    assert(P::Format(s, 0, true).empty());

    P::Sample unknown;
    unknown.upscaler = "";
    assert(P::Format(unknown, P::Upscaler | P::Gpu | P::Cpu | P::Ram | P::Vram, false) ==
           "Native\nGPU n/a\nProcess CPU n/a\nProcess RAM n/a\nVRAM n/a");
    assert(P::Format(unknown, P::Fps | P::FrameTime, false) ==
           "Presentation FPS n/a\nPresent interval n/a");
    unknown.ram_used_gb = 2.0;
    assert(P::Format(unknown, P::Ram, true) == "Process RAM 2.0 GiB");

    const char* path = "perf-overlay-test.ini";
    {
        std::ofstream out(path);
        out << "show_fps=1\noverlay_fps=0\noverlay_frametime=1\noverlay_upscaler=0\noverlay_gpu=1\n"
               "overlay_cpu=1\noverlay_ram=0\noverlay_vram=1\noverlay_scale=400\noverlay_corner=2\n"
               "overlay_opacity=-5\noverlay_layout=1\nmenu_tab=3\n";
    }
    _putenv_s("ORDER1886_CONFIG", path);
    auto& v = Ps4Settings::Get();
    assert(v.show_fps && v.overlay_layout == 1);
    assert(v.overlay_items == P::DefaultItems && v.overlay_scale == 100 && v.overlay_corner == 1);
    Ps4Settings::Load();
    assert(v.overlay_items == (P::FrameTime | P::Gpu | P::Cpu | P::Vram));
    assert(v.overlay_scale == 300 && v.overlay_corner == 2 && v.overlay_opacity == 0);
    assert(v.overlay_layout == 1 && v.menu_tab == 3);
    v.overlay_items = P::Fps | P::Ram;
    v.overlay_scale = 150;
    v.overlay_opacity = 70;
    v.menu_tab = 1;
    Ps4Settings::Save();
    const std::string saved = Read(path);
    for (const char* line : {"show_fps=1\n", "overlay_scale=150\n", "overlay_corner=2\n",
                             "overlay_opacity=70\n", "overlay_layout=1\n"}) {
        assert(saved.find(line) != std::string::npos);
    }
    {
        std::ofstream out(path);
        out << "show_fps=0\noverlay_corner=9\nmenu_tab=-1\noverlay_scale=10\n";
    }
    Ps4Settings::Load();
    assert(!v.show_fps && v.overlay_corner == 1 && v.menu_tab == 0 && v.overlay_scale == 50);
    {
        std::ofstream out(path);
        out << "presentation_filter=fsr1\nfsr1=0\nrcas=1\nupscaler=fsr4\nobject_motion=1\n";
    }
    Ps4Settings::Load();
    assert(v.fsr1 && !v.rcas && !v.object_motion && v.upscaler == Ps4Settings::UpscalerOff);
    Ps4Settings::Save();
    assert(Read(path).find("presentation_filter=fsr1\n") != std::string::npos);
    {
        std::ofstream out(path);
        out << "presentation_filter=linear\nfsr1=1\n";
    }
    Ps4Settings::Load();
    assert(!v.fsr1);
    {
        std::ofstream out(path);
        out << "presentation_filter=invalid\n";
    }
    Ps4Settings::Load();
    assert(!v.fsr1);
    std::remove(path);
    std::puts("PASS: performance overlay");
}
