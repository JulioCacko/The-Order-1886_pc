#undef NDEBUG
#include <cassert>
#include <cstdlib>
#include <cstdint>
#include "video_core/buffer_cache/region_manager.h"

extern "C" { std::uint64_t runtime_disabled_optimizations{}; }

namespace {
int reads[VideoCore::NUM_PAGES_PER_REGION]{};
int writes[VideoCore::NUM_PAGES_PER_REGION]{};
}

namespace VideoCore {
// Record protection requests; no guest pages or GPU are needed to exercise the
// production RegionManager's complete transition logic.
struct PageManager::Impl {};
PageManager::PageManager(Vulkan::Rasterizer*) {}
PageManager::~PageManager() = default;
template <bool track, bool is_read>
void PageManager::UpdatePageWatchersForRegion(VAddr, RegionBits& mask) const {
    auto& counts = is_read ? reads : writes;
    for (const auto& [first, last] : mask) {
        for (auto page=first;page<last;++page) {
            counts[page] += track ? 1 : -1;
            assert(counts[page]>=0 && counts[page]<=1);
        }
    }
}
}

int main() {
    using namespace VideoCore;
    constexpr VAddr base=0x100000;
    PageManager tracker{nullptr};
    RegionManager region{&tracker,base};
    const auto mode=EmulatorSettings.GetReadbacksMode();
    assert(mode<=GpuReadbacksMode::Selective);
    const bool precise=mode==GpuReadbacksMode::Precise;
    const bool selective=mode==GpuReadbacksMode::Selective;
    region.ChangeRegionState<Type::CPU,false>(base,3*TRACKER_BYTES_PER_PAGE);
    region.ChangeRegionState<Type::GPU,true>(base,3*TRACKER_BYTES_PER_PAGE);
    assert(reads[0]==int(precise) && reads[1]==int(precise));
    // Only the selected page becomes read-protected; repeated/overlapping watch
    // requests must not double-count it.
    region.WatchReads(base+TRACKER_BYTES_PER_PAGE,16,true);
    region.WatchReads(base+TRACKER_BYTES_PER_PAGE+8,8,true);
    assert(reads[0]==int(precise));
    assert(reads[1]==int(precise||selective));
    region.ChangeRegionState<Type::GPU,false>(base+TRACKER_BYTES_PER_PAGE,16);
    assert(!reads[1]);
    region.ChangeRegionState<Type::GPU,true>(base+TRACKER_BYTES_PER_PAGE,16);
    assert(reads[1]==int(precise||selective));
    // A CPU overwrite/unmap cancels the selective watch. It cannot cancel the
    // protection required by precise mode while the GPU still owns the bytes.
    region.WatchReads(base+TRACKER_BYTES_PER_PAGE,16,false);
    assert(reads[1]==int(precise));
    region.ChangeRegionState<Type::GPU,false>(base,3*TRACKER_BYTES_PER_PAGE);
    for (auto count:reads) assert(!count);
    region.ChangeRegionState<Type::CPU,true>(base,3*TRACKER_BYTES_PER_PAGE);
    for (auto count:writes) assert(!count);
    // Reused pages have no watch from their previous allocation.
    region.ChangeRegionState<Type::GPU,true>(base+TRACKER_BYTES_PER_PAGE,16);
    assert(reads[1]==int(precise));
    region.ChangeRegionState<Type::GPU,false>(base+TRACKER_BYTES_PER_PAGE,16);
    region.WatchReads(base,0,true);
    region.WatchReads(base+1,0,true);
    for (auto count:reads) assert(!count);
}
