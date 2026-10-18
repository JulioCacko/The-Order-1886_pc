// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <mutex>

namespace Ps4Mouse {
constexpr bool WantsCapture(bool enabled, bool released, bool blocked,
                            bool event_focus, bool native_focus) {
    return enabled && !released && !blocked && event_focus && native_focus;
}

struct Sample {
    std::uint8_t x{128}, y{128};
    std::uint32_t buttons{}; // bit 0: left mouse button; bit 1: right
};

// SDL events and capture belong to the window thread. Guest pad reads only copy
// a published sample; polling more often must not consume or amplify mouse motion.
class Input {
public:
    void Capture(bool value, double now) {
        std::scoped_lock lock{mutex};
        if (captured == value) return;
        captured = value;
        last = now;
        dx = dy = vx = vy = 0;
        sample = {};
    }
    void Motion(float x, float y) {
        std::scoped_lock lock{mutex};
        if (!captured || !std::isfinite(x) || !std::isfinite(y)) return;
        dx = std::clamp(dx + x, -100000.0, 100000.0);
        dy = std::clamp(dy + y, -100000.0, 100000.0);
    }
    void Button(std::uint32_t mask, bool down) {
        std::scoped_lock lock{mutex};
        if (!captured) return;
        if (down) sample.buttons |= mask;
        else sample.buttons &= ~mask;
    }
    void Update(double now, int sensitivity, bool invert_y) {
        std::scoped_lock lock{mutex};
        const double dt = now - last;
        if (!(dt > 0)) return;
        last = now;
        if (!captured || dt > 0.25) {
            dx = dy = vx = vy = 0;
            sample.x = sample.y = 128;
            if (!captured) sample.buttons = 0;
            return;
        }
        // Time-based smoothing, rather than displacement per rendered frame.
        const double decay = std::exp(-dt / 0.025);
        vx = decay * vx + (1 - decay) * dx / dt;
        vy = decay * vy + (1 - decay) * dy / dt;
        dx = dy = 0;
        const double gain = 0.08 * std::clamp(sensitivity, 10, 500) / 100;
        const auto axis = [gain](double speed) {
            return std::uint8_t(std::clamp(std::lround(128 + speed * gain), 0L, 255L));
        };
        sample.x = axis(vx);
        sample.y = axis(invert_y ? -vy : vy);
    }
    Ps4Mouse::Sample Sample() const {
        std::scoped_lock lock{mutex};
        return sample;
    }
private:
    mutable std::mutex mutex;
    bool captured{};
    double last{}, dx{}, dy{}, vx{}, vy{};
    Ps4Mouse::Sample sample{};
};
inline Input input;
} // namespace Ps4Mouse
