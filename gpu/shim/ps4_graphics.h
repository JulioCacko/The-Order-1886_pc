// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <algorithm>
#include <array>
#include <string_view>
namespace Ps4Graphics {
enum DisplayMode : int { Windowed = 0, Borderless = 1, Fullscreen = 2, DisplayModeCount };
inline constexpr std::array<std::string_view, DisplayModeCount> DisplayModeKeys = {
    "windowed", "borderless", "fullscreen"};
inline constexpr std::array<const char*, DisplayModeCount> DisplayModeNames = {
    "Windowed", "Borderless", "Fullscreen"};
inline constexpr std::array<int, 5> FpsLimits = {30, 60, 120, 240, 0};
inline int IndexOf(const auto& values, const auto& value, int fallback = 0) {
    for (unsigned i = 0; i < values.size(); ++i) if (values[i] == value) return int(i);
    return fallback;
}
inline int ParseDisplayMode(std::string_view value) { return IndexOf(DisplayModeKeys, value); }
/// 0 is uncapped; any other cap is honoured within the launcher's 30-240 range (FpsLimits are
/// only the menu's presets).
inline int ParseFpsLimit(int value) { return value <= 0 ? 0 : std::clamp(value, 30, 240); }
inline constexpr std::array<int, 5> Anisotropies = {0, 2, 4, 8, 16};
inline int ParseAnisotropy(int value) { return IndexOf(Anisotropies, value, -1) >= 0 ? value : 0; }
inline constexpr std::array<int, 3> FramesQueued = {1, 2, 0};
inline int ParseFramesQueued(int value) { return IndexOf(FramesQueued, value, -1) >= 0 ? value : 1; }
inline int ParseRcasStrength(int value) { return value >= 0 && value <= 100 ? value : 75; }
inline float RcasAttenuation(int strength) {
    return 2.0f * (1.0f - float(ParseRcasStrength(strength)) / 100.0f);
}
inline bool FsrPassRuns(bool fsr1, bool rcas, int in_w, int in_h, int out_w, int out_h) {
    return (fsr1 && in_w < out_w && in_h < out_h) || (rcas && in_w == out_w && in_h == out_h);
}
} // namespace Ps4Graphics
