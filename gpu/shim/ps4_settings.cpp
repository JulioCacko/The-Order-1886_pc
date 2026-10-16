// SPDX-License-Identifier: GPL-2.0-or-later
#include "ps4_settings.h"
#include "ps4_graphics.h"

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <string_view>

namespace Ps4Settings {

namespace {

const char* Path() {
    const char* env = std::getenv("ORDER1886_CONFIG");
    return env && env[0] ? env : "order1886.ini";
}

float Clamp(float v, float lo, float hi) {
    return std::clamp(v, lo, hi);
}

void Set(Values& v, const std::string& key, const std::string& value) {
    const float f = float(std::atof(value.c_str()));
    const int i = std::atoi(value.c_str());
    static const char* const overlay_keys[] = {"overlay_fps", "overlay_frametime", "overlay_upscaler",
                                               "overlay_gpu", "overlay_cpu", "overlay_ram", "overlay_vram"};
    for (unsigned item = 0; item < 7; ++item) {
        if (key == overlay_keys[item]) {
            const unsigned bit = 1u << item;
            v.overlay_items = i ? (v.overlay_items | bit) : (v.overlay_items & ~bit);
            return;
        }
    }
    if (key == "overlay_scale") {
        v.overlay_scale = std::clamp(i, 50, 300);
        return;
    }
    if (key == "overlay_corner") {
        v.overlay_corner = i >= 0 && i <= 3 ? i : 1;
        return;
    }
    if (key == "overlay_opacity") {
        v.overlay_opacity = std::clamp(i, 0, 100);
        return;
    }
    if (key == "overlay_layout") {
        v.overlay_layout = i == 1 ? 1 : 0;
        return;
    }
    if (key == "menu_tab") {
        v.menu_tab = i >= 0 && i <= 3 ? i : 0;
        return;
    }
    if (key == "upscaler") {
        for (int u = 0; u < UpscalerCount; ++u) {
            if (value == UpscalerName(u)) {
                v.upscaler = u;
            }
        }
    } else if (key == "preset") {
        v.preset = std::clamp(i, 0, PresetCount - 1);
    } else if (key == "sharpen") {
        v.sharpen = i != 0;
    } else if (key == "sharpness") {
        v.sharpness = Clamp(f, 0.0f, 2.0f);
    } else if (key == "jitter") {
        v.jitter = i != 0;
    } else if (key == "reactive") {
        v.reactive = i != 0;
    } else if (key == "object_motion") {
        v.object_motion = i != 0;
    } else if (key == "reactive_scale") {
        v.reactive_scale = Clamp(f, 0.0f, 16.0f);
    } else if (key == "reactive_threshold") {
        v.reactive_threshold = Clamp(f, 0.0f, 1.0f);
    } else if (key == "reactive_max") {
        v.reactive_max = Clamp(f, 0.0f, 1.0f);
    } else if (key == "debug_view") {
        v.debug_view = std::clamp(i, 0, DebugViewCount - 1);
    } else if (key == "show_fps") {
        v.show_fps = i != 0;
    } else if (key == "display_mode") {
        v.display_mode = Ps4Graphics::ParseDisplayMode(value);
    } else if (key == "vsync") {
        v.vsync = i != 0;
    } else if (key == "fps_limit") {
        v.fps_limit = Ps4Graphics::ParseFpsLimit(i);
    } else if (key == "async_shaders") {
        v.async_shaders = i != 0;
    } else if (key == "presentation_filter") {
        v.fsr1 = value == "fsr1";
    } else if (key == "fsr1") {
        // Legacy engine switches do not override the explicit presentation filter.
        return;
    } else if (key == "rcas") {
        v.rcas = i != 0;
    } else if (key == "rcas_strength") {
        v.rcas_strength = Ps4Graphics::ParseRcasStrength(value.empty() ? -1 : i);
    } else if (key == "frames_queued") {
        v.frames_queued = Ps4Graphics::ParseFramesQueued(value.empty() ? -1 : i);
    }   else if (key == "deferred_readback") {
        v.deferred_readback = i != 0;
    } else if (key == "stale_readback") {
        v.stale_readback = i != 0;
    } else if (key == "anisotropy") {
        v.anisotropy = Ps4Graphics::ParseAnisotropy(i);
    } else if (key == "vibration") {
        v.vibration = value.empty() ? 100 : std::clamp(i, 0, 100);
    } else if (key == "restart_unconfirmed") {
        v.restart_unconfirmed = i != 0;

    } else if (key == "fsr4_auto_exposure") {
        v.fsr4_auto_exposure = i != 0;
    } else if (key == "fsr4_invert_jitter") {
        v.fsr4_invert_jitter = i != 0;
    } else if (key == "live_resolution") {
        v.live_resolution = value == "auto" ? -1 : std::clamp(i, 0, 1);
    } else if (key == "output_res") {
        for (int r = 0; r < OutputCount; ++r) {
            if (value == std::to_string(OutputWidths[r]) + "x" + std::to_string(OutputHeights[r])) {
                v.output_res = r;
            }
        }
    }
}

} // namespace

Values& Get() {
    static Values values;
    return values;
}

void Load() {
    auto& v = Get();
    v.fsr1 = false;
    if (FILE* file = std::fopen(Path(), "r")) {
        char line[256];
        while (std::fgets(line, sizeof(line), file)) {
            std::string text{line};
            text.erase(text.find_last_not_of(" \t\r\n") + 1);
            const auto eq = text.find('=');
            if (text.empty() || text[0] == '#' || eq == std::string::npos) {
                continue;
            }
            Set(v, text.substr(0, eq), text.substr(eq + 1));
        }
        std::fclose(file);
        std::printf("Settings: %s\n", Path());
    }
    // Environment overrides (scripts, A/B tests).
    if (const char* env = std::getenv("ORDER1886_UPSCALER")) {
        v.upscaler = UpscalerOff;
        for (int u = 0; u < UpscalerCount; ++u) {
            if (std::strcmp(env, UpscalerName(u)) == 0) v.upscaler = u;
        }
    }
    const std::pair<const char*, const char*> env_keys[] = {
        {"ORDER1886_FSR_SHARPNESS", "sharpness"},        {"ORDER1886_JITTER", "jitter"},
        {"ORDER1886_REACTIVE", "reactive"},              {"ORDER1886_REACTIVE_SCALE", "reactive_scale"},
        {"ORDER1886_REACTIVE_THRESHOLD", "reactive_threshold"}, {"ORDER1886_REACTIVE_MAX", "reactive_max"},
        {"ORDER1886_UPSCALE_PRESET", "preset"},            {"ORDER1886_OBJECT_MOTION", "object_motion"},
        {"ORDER1886_ASYNC_SHADERS", "async_shaders"},      {"ORDER1886_DEFERRED_READBACK", "deferred_readback"},
        {"ORDER1886_STALE_READBACK", "stale_readback"},     {"ORDER1886_FSR1", "fsr1"},
        {"ORDER1886_RCAS", "rcas"},                        {"ORDER1886_FRAMES_AHEAD", "frames_queued"},
        {"ORDER1886_ANISOTROPY", "anisotropy"},            {"ORDER1886_VIBRATION", "vibration"},
    };
    for (const auto& [env, key] : env_keys) {
        if (const char* value = std::getenv(env); value && value[0]) {
            Set(v, key, value);
        }
    }
    // No inherited engine reconstruction, cheats, HUD, or speculative readbacks.
    v.upscaler = UpscalerOff;
    v.object_motion = false;
    v.jitter = false;
    v.rcas = false;
    v.live_resolution = 0;
    v.async_shaders = false;
    v.deferred_readback = false;
    v.stale_readback = false;
    v.startup_preset = v.preset;
    v.startup_upscaler = v.upscaler;
    v.startup_object_motion = v.object_motion;
    v.startup_output_res = v.output_res;
    v.startup_live_resolution = v.live_resolution;
    v.startup_deferred_readback = v.deferred_readback;
    v.startup_stale_readback = v.stale_readback;
    v.startup_anisotropy = v.anisotropy;
}

bool GraphicsNeedRestart() {
    const auto& v = Get();
    return v.deferred_readback != v.startup_deferred_readback ||
           v.stale_readback != v.startup_stale_readback ||
           v.anisotropy != v.startup_anisotropy;
}

void ConfigureUpscalerSupport(bool fsr4, bool fsr411) {
    auto& v = Get();
    v.fsr4_supported = fsr4;
    v.fsr411_supported = fsr4 && fsr411;
    const int requested = v.upscaler;
    if ((requested == UpscalerFsr4 && !v.fsr4_supported) ||
        (requested == UpscalerFsr411 && !v.fsr411_supported)) {
        v.fsr4_problem = "GPU does not support the selected FSR 4 shaders; using FSR 3.1";
        std::printf("Upscaler: %s unsupported on this GPU; falling back to FSR 3.1 before the first frame\n",
                    UpscalerName(requested));
        v.upscaler = UpscalerFsr3;
    }
}

void ConfigureDlssSupport(bool available, const char* problem) {
    auto& v = Get();
    v.dlss_supported = available;
    static std::string kept;
    kept = problem ? problem : "";
    v.dlss_problem = available || kept.empty() ? nullptr : kept.c_str();
    if (v.upscaler == UpscalerDlss && !available) {
        std::printf("Upscaler: DLSS unavailable (%s); falling back to FSR 3.1\n",
                    kept.empty() ? "ps4_dlss.dll or nvngx_dlss.dll missing" : kept.c_str());
        v.upscaler = UpscalerFsr3;
    }
}

bool FixedRenderSession() {
    const char* size = std::getenv("ORDER1886_RENDER_RES");
    return size && size[0];
}





void Save() {
    const auto& v = Get();
    FILE* file = std::fopen(Path(), "w");
    if (!file) { std::printf("Settings: cannot write %s\n", Path()); return; }
    std::fprintf(file,
        "# The Order: 1886 runtime settings\n"
        "display_mode=%s\nvsync=%d\nfps_limit=%d\nframes_queued=%d\npresentation_filter=%s\n"
        "vibration=%d\nanisotropy=%d\nshow_fps=%d\n"
        "overlay_scale=%d\noverlay_corner=%d\noverlay_opacity=%d\noverlay_layout=%d\n",
        Ps4Graphics::DisplayModeKeys[std::clamp(v.display_mode.load(), 0, 2)].data(),
        int(v.vsync.load()), v.fps_limit.load(), v.frames_queued.load(),
        v.fsr1.load() ? "fsr1" : "linear",
        v.vibration.load(), v.anisotropy.load(), int(v.show_fps.load()),
        v.overlay_scale.load(), v.overlay_corner.load(), v.overlay_opacity.load(), v.overlay_layout.load());
    std::fclose(file);
}

float PresetScale(int preset) {
    static constexpr float scales[PresetCount] = {1.0f, 1.5f, 1.7f, 2.0f, 3.0f};
    return scales[std::clamp(preset, 0, PresetCount - 1)];
}

const char* PresetName(int preset) {
    static constexpr const char* names[PresetCount] = {"Native AA", "Quality", "Balanced",
                                                       "Performance", "Ultra Performance"};
    return names[std::clamp(preset, 0, PresetCount - 1)];
}

const char* UpscalerName(int upscaler) {
    static constexpr const char* names[UpscalerCount] = {"off", "fsr3", "fsr4", "fsr411", "taa", "dlss"};
    return names[std::clamp(upscaler, 0, UpscalerCount - 1)];
}

} // namespace Ps4Settings
