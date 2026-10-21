// SPDX-License-Identifier: GPL-2.0-or-later
//
// Platform::IrqController is shared by guest threads (sceGnmAddEqEvent registers handlers) and
// the GPU thread (Signal on end-of-pipe, flip and idle). Each controller here starts empty, so
// every Register and Signal can be the first use of its interrupt and the controller's storage
// is filled from two threads at once. Before the fix that storage was an unsynchronised
// unordered_map: a concurrent insert could rehash it under the other thread and corrupt the
// heap, which in the game surfaced as crashes in unrelated structures soon after launch.
#include <atomic>
#include <cassert>
#include <cstdio>
#include <memory>
#include <thread>
#include <vector>
#include "core/platform.h"

using Platform::InterruptId;

int main() {
    constexpr InterruptId ids[] = {
        InterruptId::Compute0RelMem, InterruptId::Compute1RelMem, InterruptId::Compute2RelMem,
        InterruptId::Compute3RelMem, InterruptId::Compute4RelMem, InterruptId::Compute5RelMem,
        InterruptId::Compute6RelMem, InterruptId::GfxFlip,        InterruptId::GpuIdle,
        InterruptId::GfxEop};
    std::atomic<int> handled{0};
    for (int round = 0; round < 2000; ++round) {
        auto irq = std::make_unique<Platform::IrqController>();
        std::atomic<bool> go{false};
        std::vector<int> uids(std::size(ids));
        std::thread guest([&] {
            while (!go.load()) {
            }
            for (size_t i = 0; i < std::size(ids); ++i) {
                irq->Register(ids[i], [&](InterruptId) { ++handled; }, &uids[i]);
            }
        });
        std::thread gpu([&] {
            while (!go.load()) {
            }
            for (size_t i = std::size(ids); i-- > 0;) {
                irq->Signal(ids[i]);
            }
        });
        go = true;
        guest.join();
        gpu.join();
        // Every handler is registered exactly once and still fires after the race.
        for (const auto id : ids) {
            irq->Signal(id);
        }
    }
    assert(handled.load() >= 2000 * int(std::size(ids)));
    std::puts("PASS: IRQ controller survives concurrent first use");
}
