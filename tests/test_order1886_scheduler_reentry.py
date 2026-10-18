"""CPU-only regression harness for the actual scheduler recording methods.

The Vulkan command-buffer handle is a test double. RecordChunk, Record,
ReserveRecordData, RecordData and KickRecording are extracted verbatim.
AcquireChunk is also extracted, with instrumentation only at function entry and
the fresh-allocation expression. Its real pool locking remains intact.
No graphics driver or game is started.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCHEDULER = ROOT / "gpu/shadps4/video_core/renderer_vulkan/vk_scheduler"


def definition(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 1
    for end in range(opening + 1, len(source)):
        depth += (source[end] == "{") - (source[end] == "}")
        if depth == 0:
            return source[start:end + 1]
    raise AssertionError(f"Unterminated production definition: {signature}")


PREAMBLE = r"""
#include <array>
#include <atomic>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <deque>
#include <functional>
#include <iostream>
#include <memory>
#include <mutex>
#include <span>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>
#define ASSERT(value) assert(value)
namespace vk { using CommandBuffer = int; }
namespace Ps4Toggle {
enum Toggle { ThreadedRecording, RecordPrefetch };
bool disable_recording = false;
bool Disabled(Toggle toggle) { return toggle == RecordPrefetch || disable_recording; }
}
"""

SCHEDULER_STUB = r"""
class Scheduler {
public:
    bool recording_threaded = true;
    bool direct_mode = false;
    vk::CommandBuffer current_cmdbuf = 17;
    std::unique_ptr<RecordChunk> record_chunk = std::make_unique<RecordChunk>();
    std::vector<std::unique_ptr<RecordChunk>> full_chunks;
    std::vector<std::unique_ptr<RecordChunk>> free_chunks;
    std::deque<std::unique_ptr<RecordChunk>> recorder_queue;
    std::mutex recorder_mutex;
    struct { int notifications = 0; void notify_one() { ++notifications; } } recorder_cv;
    bool recorder_sleeping = true;
    std::atomic<size_t> queued_chunks{};
    std::function<void()> during_acquire;
    int acquisitions = 0;
    int fresh_allocations = 0;
    int synchronizations = 0;

    std::unique_ptr<RecordChunk> AcquireChunk();
    std::unique_ptr<RecordChunk> AllocateFreshChunk() {
        ++fresh_allocations;
        if (auto hook = std::exchange(during_acquire, {})) {
            if (!record_chunk) throw std::runtime_error("record_chunk is null during reentry");
            hook();
        }
        return std::make_unique<RecordChunk>();
    }
    void SyncRecording() { ++synchronizations; KickRecording(true); Drain(); }
    void KickRecording(bool force = false);

    void CheckOwnership() {
        assert(record_chunk);
        std::vector<const RecordChunk*> owners{record_chunk.get()};
        auto check = [&](const auto& chunk) {
            assert(chunk);
            for (auto* owner : owners) assert(owner != chunk.get());
            owners.push_back(chunk.get());
        };
        for (const auto& chunk : full_chunks) check(chunk);
        for (const auto& chunk : recorder_queue) check(chunk);
    }
    bool InCurrentChunk(const void* data) const {
        const auto address = reinterpret_cast<std::uintptr_t>(data);
        const auto begin = reinterpret_cast<std::uintptr_t>(record_chunk.get());
        return address >= begin && address < begin + sizeof(RecordChunk);
    }
    void Drain() {
        while (!recorder_queue.empty()) {
            auto chunk = std::move(recorder_queue.front());
            recorder_queue.pop_front();
            chunk->Execute(current_cmdbuf);
            // Destruction here makes later commands expose cross-chunk data ownership bugs.
        }
        queued_chunks.store(0);
    }
    void FillCurrent() {
        assert(record_chunk->Allocate(RecordChunk::Capacity - record_chunk->Size(), 1));
    }
"""

CASES = r"""
void CheckEvents(const std::vector<int>& events, std::initializer_list<int> expected) {
    assert(events == std::vector<int>(expected));
}

int main(int argc, char** argv) {
    try {
        assert(argc == 2);
        const std::string scenario = argv[1];
        Scheduler scheduler;
        std::vector<int> events;
        auto command = [&](int event) {
            return [&, event](vk::CommandBuffer handle) {
                assert(handle == 17);
                events.push_back(event);
            };
        };
        if (scenario == "record") {
            scheduler.Record(command(0));
            scheduler.FillCurrent();
            scheduler.during_acquire = [&] { scheduler.Record(command(1)); };
            scheduler.Record(command(2));
            assert(scheduler.acquisitions == 2); // Nested rollover, then outer rollover.
            scheduler.CheckOwnership();
            assert(events.empty());
            scheduler.KickRecording(true);
            scheduler.Drain();
            CheckEvents(events, {0, 1, 2});
        } else if (scenario == "reserve") {
            scheduler.Record(command(0));
            scheduler.FillCurrent();
            scheduler.during_acquire = [&] {
                std::array<int, 3> source{10, 20, 30};
                auto data = scheduler.RecordData<int>(source);
                assert(scheduler.InCurrentChunk(data.data()));
                scheduler.Record([&, data](vk::CommandBuffer) {
                    assert(data[0] == 10 && data[1] == 20 && data[2] == 30);
                    events.push_back(1);
                });
                source.fill(-1);
            };
            std::array<int, 3> source{40, 50, 60};
            auto data = scheduler.RecordData<int>(source);
            assert(scheduler.InCurrentChunk(data.data()));
            scheduler.Record([&, data](vk::CommandBuffer) {
                assert(data[0] == 40 && data[1] == 50 && data[2] == 60);
                events.push_back(2);
            });
            source.fill(-1);
            assert(scheduler.acquisitions == 2);
            scheduler.CheckOwnership();
            scheduler.KickRecording(true);
            scheduler.Drain();
            CheckEvents(events, {0, 1, 2});
        } else if (scenario == "kick") {
            scheduler.Record(command(0));
            scheduler.during_acquire = [&] { scheduler.Record(command(1)); };
            scheduler.KickRecording(true);
            scheduler.CheckOwnership();
            assert(scheduler.queued_chunks.load() == 1);
            assert(scheduler.recorder_cv.notifications == 1);
            assert(scheduler.record_chunk->Empty());
            scheduler.Record(command(2));
            scheduler.KickRecording(true);
            scheduler.Drain();
            CheckEvents(events, {0, 1, 2});
        } else if (scenario == "kick-nested-rollover") {
            scheduler.Record(command(0));
            scheduler.FillCurrent();
            scheduler.during_acquire = [&] { scheduler.Record(command(1)); };
            scheduler.KickRecording(true);
            scheduler.CheckOwnership();
            assert(scheduler.queued_chunks.load() == 2);
            scheduler.Record(command(2));
            scheduler.KickRecording(true);
            scheduler.Drain();
            CheckEvents(events, {0, 1, 2});
        } else if (scenario == "early-returns") {
            auto* original = scheduler.record_chunk.get();
            scheduler.KickRecording(true); // No recorded commands.
            scheduler.Record(command(0));
            scheduler.KickRecording(false); // Small batch remains on producer.
            assert(scheduler.record_chunk.get() == original);
            assert(scheduler.acquisitions == 0 && scheduler.recorder_queue.empty());
            scheduler.recording_threaded = false;
            scheduler.ReserveRecordData(4);
            std::array<int, 1> source{5};
            assert(scheduler.RecordData<int>(source).data() == source.data());
            scheduler.Record(command(1));
            scheduler.KickRecording(true); // Disabled recorder remains untouched.
            CheckEvents(events, {1});
            scheduler.recording_threaded = true;
            scheduler.KickRecording(true);
            scheduler.Drain();
            CheckEvents(events, {1, 0});
        } else if (scenario == "full-chunks-empty-current") {
            scheduler.Record(command(0));
            scheduler.FillCurrent();
            scheduler.ReserveRecordData(4); // Retires old chunk, leaves current empty.
            assert(scheduler.record_chunk->Empty());
            auto* empty = scheduler.record_chunk.get();
            const auto acquired = scheduler.acquisitions;
            scheduler.recorder_sleeping = false;
            scheduler.KickRecording(false);
            scheduler.CheckOwnership();
            assert(scheduler.record_chunk.get() == empty);
            assert(scheduler.acquisitions == acquired);
            assert(scheduler.recorder_cv.notifications == 0);
            assert(scheduler.queued_chunks.load() == 1);
            scheduler.Drain();
            CheckEvents(events, {0});
        } else if (scenario == "direct-mode") {
            scheduler.direct_mode = true;
            scheduler.Record(command(0));
            scheduler.ReserveRecordData(4);
            assert(scheduler.acquisitions == 0);
            scheduler.direct_mode = false;
            Ps4Toggle::disable_recording = true;
            scheduler.Record(command(1));
            assert(scheduler.synchronizations == 1 && scheduler.direct_mode);
            CheckEvents(events, {0, 1});
        } else if (scenario == "pooled-chunks") {
            auto first = std::make_unique<RecordChunk>();
            auto second = std::make_unique<RecordChunk>();
            auto* first_identity = first.get();
            auto* second_identity = second.get();
            scheduler.free_chunks.push_back(std::move(first));
            scheduler.free_chunks.push_back(std::move(second));
            bool allocation_hook_called = false;
            scheduler.during_acquire = [&] { allocation_hook_called = true; };
            auto newest = scheduler.AcquireChunk();
            auto oldest = scheduler.AcquireChunk();
            assert(newest.get() == second_identity && oldest.get() == first_identity);
            assert(scheduler.free_chunks.empty());
            assert(scheduler.acquisitions == 2 && scheduler.fresh_allocations == 0);
            assert(!allocation_hook_called && scheduler.during_acquire);
            assert(newest->Push(command(0)) && oldest->Push(command(1)));
            newest->Execute(scheduler.current_cmdbuf);
            oldest->Execute(scheduler.current_cmdbuf);
            auto fresh = scheduler.AcquireChunk();
            assert(fresh && fresh.get() != newest.get() && fresh.get() != oldest.get());
            assert(scheduler.fresh_allocations == 1 && allocation_hook_called);
            CheckEvents(events, {0, 1});
        } else {
            throw std::runtime_error("unknown scenario");
        }
        scheduler.CheckOwnership();
        std::cout << scenario << " passed\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
"""


class SchedulerReentryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("clang++") or shutil.which("g++")
        fallback = Path("C:/msys64/clang64/bin/clang++.exe")
        if compiler is None and fallback.is_file():
            compiler = str(fallback)
        if compiler is None:
            raise unittest.SkipTest("A C++23 compiler is required for the production-method CPU harness")
        cls.temporary = tempfile.TemporaryDirectory(prefix="Order scheduler reentry ")
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        cls.binary = directory / ("scheduler_reentry.exe" if os.name == "nt" else "scheduler_reentry")
        header = SCHEDULER.with_suffix(".h").read_text(encoding="utf-8")
        implementation = SCHEDULER.with_suffix(".cpp").read_text(encoding="utf-8")
        methods = [definition(header, "template <typename Func>\n    void Record(Func&& func)"),
                   definition(header, "bool IsRecordingDeferred() const noexcept"),
                   definition(header, "void ReserveRecordData(size_t bytes)"),
                   definition(header, "template <typename T>\n    std::span<const T> RecordData")]
        if "void RetireChunk()" in header:
            methods.append(definition(header, "void RetireChunk()"))
        acquire = definition(implementation, "std::unique_ptr<RecordChunk> Scheduler::AcquireChunk()")
        allocation = "std::make_unique<RecordChunk>()"
        if acquire.count(allocation) != 1:
            raise AssertionError("AcquireChunk fresh-allocation boundary changed; update the harness")
        acquire = acquire.replace("{", "{\n    ++acquisitions;", 1)
        acquire = acquire.replace(allocation, "AllocateFreshChunk()")
        code = (PREAMBLE + definition(header, "class RecordChunk {") + ";\n"
                + SCHEDULER_STUB + "\n".join(methods) + "};\n"
                + acquire + "\n"
                + definition(implementation, "void Scheduler::KickRecording(bool force)") + CASES)
        source = directory / "scheduler_reentry.cpp"
        source.write_text(code, encoding="utf-8")
        cls.environment = dict(os.environ)
        cls.environment["PATH"] = str(Path(compiler).parent) + os.pathsep + cls.environment.get("PATH", "")
        result = subprocess.run([compiler, "-std=c++23", "-UNDEBUG", "-O0", str(source),
                                 "-o", str(cls.binary)], capture_output=True, text=True,
                                env=cls.environment, timeout=90)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def check_scenario(self, scenario):
        try:
            # subprocess.run kills and waits for a timed-out child before raising,
            # so deadlock regressions cannot retain the executable or temporary tree.
            result = subprocess.run([str(self.binary), scenario], capture_output=True, text=True,
                                    env=self.environment, timeout=3)
        except subprocess.TimeoutExpired:
            self.fail(f"{scenario}: scheduler deadlocked at fresh-allocation reentry (3s timeout)")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_record_nested_rollover_preserves_nonnull_state_and_execution_order(self):
        self.check_scenario("record")

    def test_record_data_nested_reservation_keeps_data_with_owning_command(self):
        self.check_scenario("reserve")

    def test_kick_reentry_publishes_commands_in_order_and_replaces_current(self):
        self.check_scenario("kick")

    def test_kick_reentry_can_retire_another_full_chunk_without_losing_it(self):
        self.check_scenario("kick-nested-rollover")

    def test_empty_small_and_disabled_recording_paths_do_not_acquire(self):
        self.check_scenario("early-returns")

    def test_full_chunks_publish_without_replacing_empty_current_or_waking_busy_worker(self):
        self.check_scenario("full-chunks-empty-current")

    def test_direct_and_disabled_toggle_paths_keep_existing_sync_behavior(self):
        self.check_scenario("direct-mode")

    def test_pool_reuses_chunks_without_allocating_and_allocates_only_when_empty(self):
        self.check_scenario("pooled-chunks")


if __name__ == "__main__":
    unittest.main()
