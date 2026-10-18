// SPDX-License-Identifier: GPL-2.0-or-later
#include <cassert>
#include <cmath>
#include <cstdio>
#include <limits>
#include "ps4_mouse.h"

int main() {
    assert(Ps4Mouse::WantsCapture(true, false, false, true, true));
    assert(!Ps4Mouse::WantsCapture(true, false, false, false, true));
    assert(!Ps4Mouse::WantsCapture(true, false, false, true, false));
    assert(!Ps4Mouse::WantsCapture(true, true, false, true, true));
    assert(!Ps4Mouse::WantsCapture(true, false, true, true, true));
    assert(!Ps4Mouse::WantsCapture(false, false, false, true, true));
    Ps4Mouse::Input focus_race;
    focus_race.Capture(Ps4Mouse::WantsCapture(true, false, false, true, true), 0);
    focus_race.Motion(100, 100);
    focus_race.Button(3, true);
    // A focus gain is already queued, so native flags remain true at the lost event.
    focus_race.Capture(Ps4Mouse::WantsCapture(true, false, false, false, true), 0.01);
    assert(focus_race.Sample().x == 128 && focus_race.Sample().buttons == 0);
    focus_race.Capture(Ps4Mouse::WantsCapture(true, false, false, true, true), 0.02);
    focus_race.Update(0.03, 100, false);
    assert(focus_race.Sample().x == 128 && focus_race.Sample().y == 128);
    Ps4Mouse::Input input;
    auto sample = input.Sample();
    assert(sample.x == 128 && sample.y == 128 && sample.buttons == 0);
    input.Motion(1000, 1000);
    input.Button(1, true);
    input.Update(1, 100, false);
    assert(input.Sample().x == 128 && input.Sample().buttons == 0);
    input.Capture(true, 1);
    input.Motion(10, -10);
    input.Button(1, true);
    input.Update(1.01, 100, false);
    sample = input.Sample();
    assert(sample.x > 128 && sample.y < 128 && sample.buttons == 1);
    assert(input.Sample().x == sample.x); // several guest pad reads do not consume motion
    input.Update(1.02, 200, true);
    assert(input.Sample().x > 128 && input.Sample().y > 128);
    input.Update(1.5, 100, false);
    assert(input.Sample().x == 128 && input.Sample().buttons == 1);
    input.Capture(false, 1.03);
    assert(input.Sample().x == 128 && input.Sample().y == 128 && input.Sample().buttons == 0);
    input.Motion(100000, 100000);
    input.Capture(true, 2);
    input.Update(2.01, 100, false);
    assert(input.Sample().x == 128 && input.Sample().y == 128);
    input.Motion(std::numeric_limits<float>::quiet_NaN(), 0);
    input.Update(2.02, 100, false);
    assert(input.Sample().x == 128);
    for (int fps : {30, 60, 120, 240}) {
        Ps4Mouse::Input moving;
        moving.Capture(true, 0);
        for (int i = 1; i <= fps; ++i) {
            moving.Motion(600.0f / fps, -600.0f / fps);
            moving.Update(double(i) / fps, 100, false);
        }
        assert(std::abs(int(moving.Sample().x) - 176) <= 1);
        assert(std::abs(int(moving.Sample().y) - 80) <= 1);
        for (int i = 1; i <= fps; ++i) moving.Update(1 + double(i) / fps, 100, false);
        assert(moving.Sample().x == 128 && moving.Sample().y == 128);
    }
    std::puts("PASS: mouse motion, focus reset, inversion, buttons and poll-rate independence");
}
