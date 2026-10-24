// SPDX-FileCopyrightText: Copyright 2024 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include <chrono>
#include <array>
#include <map>
#include <unordered_map>
#include <algorithm>
#include <bit>
#include <cstdlib>
#include <magic_enum/magic_enum.hpp>
#include "ps4_copy.h"
#include "ps4_toggles.h"
#include "common/alignment.h"
#include "core/memory.h"
#include "video_core/amdgpu/liverpool.h"
#include "video_core/buffer_cache/buffer.h"
#include "video_core/buffer_cache/buffer_cache.h"
#include "video_core/buffer_cache/deferred_readback_merge.h"
#include "video_core/buffer_cache/memory_tracker.h"
#include "video_core/renderer_vulkan/vk_graphics_pipeline.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"

#include <vk_mem_alloc.h>

namespace VideoCore {

static constexpr size_t GDS_BUFFER_SIZE = 64_KB;
static constexpr size_t STREAM_BUFFER_SIZE = 128_MB;

static constexpr auto ARENA_USAGE =
    vk::BufferUsageFlagBits::eTransferSrc | vk::BufferUsageFlagBits::eTransferDst |
    vk::BufferUsageFlagBits::eUniformBuffer | vk::BufferUsageFlagBits::eStorageBuffer |
    vk::BufferUsageFlagBits::eIndexBuffer | vk::BufferUsageFlagBits::eVertexBuffer |
    vk::BufferUsageFlagBits::eIndirectBuffer | vk::BufferUsageFlagBits::eShaderDeviceAddress;

std::optional<u32> FindMemoryType(const vk::PhysicalDeviceMemoryProperties& properties,
                                  vk::MemoryPropertyFlags wanted, u32 memory_type_bits) {
    for (u32 i = 0; i < properties.memoryTypeCount; ++i) {
        if (((memory_type_bits >> i) & 1) == 0) {
            continue;
        }
        const auto flags = properties.memoryTypes[i].propertyFlags;
        if ((flags & wanted) == wanted) {
            return i;
        }
    }
    return std::nullopt;
}

BufferCache::BufferCache(const Vulkan::Instance& instance_, Vulkan::Scheduler& scheduler_,
                         Vulkan::Runtime& runtime_, AmdGpu::Liverpool* liverpool_,
                         TextureCache& texture_cache_, PageManager& tracker)
    : instance{instance_}, scheduler{scheduler_}, runtime{runtime_},
      staging_pool{runtime_.GetStagingPool()}, liverpool{liverpool_},
      memory{Core::Memory::Instance()}, texture_cache{texture_cache_},
      memory_tracker{std::make_unique<MemoryTracker>(tracker)},
      stream_buffer{instance, scheduler, MemoryType::Stream, STREAM_BUFFER_SIZE},
      gds_buffer{instance, 0, GDS_BUFFER_SIZE, MemoryType::Stream, "GDS Buffer"},
      memory_semaphore{instance} {
    while (arena_page_bits > MIN_ARENA_PAGE_BITS &&
           (u64{2} << arena_page_bits) > instance.GetMaxBufferSize()) {
        --arena_page_bits;
    }
    arena_page_size = u64{1} << arena_page_bits;
    num_arena_pages = u64{1} << (ADDRESS_SPACE_BITS - arena_page_bits);
    if (arena_page_bits != MAX_ARENA_PAGE_BITS) {
        LOG_INFO(Render_Vulkan, "Buffer arenas of {} MiB (driver buffer limit {} MiB)",
                 arena_page_size >> 20, instance.GetMaxBufferSize() >> 20);
    }
    const vk::BufferCreateInfo probe_ci = {
        .flags =
            vk::BufferCreateFlagBits::eSparseBinding | vk::BufferCreateFlagBits::eSparseResidency,
        .size = arena_page_size,
        .usage = ARENA_USAGE,
        .sharingMode = vk::SharingMode::eExclusive,
    };
    const vk::DeviceBufferMemoryRequirements req_info = {
        .pCreateInfo = &probe_ci,
    };
    const auto device = instance.GetDevice();
    const auto reqs = device.getBufferMemoryRequirements(req_info).memoryRequirements;
    block_size = Common::AlignUp(std::max<u64>(reqs.alignment, MIN_BLOCK_SIZE), reqs.alignment);
    ASSERT_MSG(std::popcount(block_size) == 1, "Sparse block size {} is not a power of 2",
               block_size);
    block_shift = std::bit_width(block_size) - 1;
    blocks_per_arena_page = arena_page_size / block_size;
    blocks_per_arena_page_shift = arena_page_bits - block_shift;
    arena_memory_type_index =
        FindMemoryType(instance.GetMemoryProperties(), vk::MemoryPropertyFlagBits::eDeviceLocal,
                       reqs.memoryTypeBits)
            .value();

    const u64 bda_pagetable_size =
        (blocks_per_arena_page * num_arena_pages) * sizeof(vk::DeviceAddress);
    fault_manager = std::make_unique<FaultManager>(instance, scheduler, *this, block_shift,
                                                   blocks_per_arena_page * num_arena_pages);
    bda_pagetable_buffer = std::make_unique<Buffer>(
        instance, 0, bda_pagetable_size, MemoryType::DeviceLocal, "BDA Page Table Buffer");
    runtime.FillBuffer(bda_pagetable_buffer.get(), 0u, bda_pagetable_size, 0u);
    // Write faults beside GPU-written bytes are deferred instead of waiting for the whole GPU.
    // Relaxed readbacks only: the snapshot reads guest pages that the other modes keep
    // read-protected. Known gap: a CPU write of a pending byte's snapshot value (or one racing
    // ApplyDeferredBatch) is not detected and the GPU data replaces it; the page has to stay
    // writable for the faulting write, so closing it needs the GPU wait this removes.
    if (const char* env = std::getenv("ORDER1886_DEFER_BUFFER_READBACK"); env && env[0] == '0') {
        deferred_readbacks_enabled = false;
    }
    deferred_readbacks_enabled = deferred_readbacks_enabled &&
                                 EmulatorSettings.GetReadbacksMode() == GpuReadbacksMode::Relaxed;
}

BufferCache::~BufferCache() = default;

bool BufferCache::ReadbackLog() {
    static const bool enabled = [] {
        const char* env = std::getenv("ORDER1886_READBACK_LOG");
        return env && *env == '1';
    }();
    return enabled;
}

u64 BufferCache::WriterOf(VAddr address) {
    std::scoped_lock lock{writers_mutex};
    auto it = writers.upper_bound(address);
    if (it == writers.begin()) {
        return 0;
    }
    --it;
    return address < it->first + it->second.first ? it->second.second : 0;
}

void BufferCache::InvalidateMemory(VAddr device_addr, u64 size, bool assume_locks) {
    memory_tracker->InvalidateRegion(device_addr, size, [this, device_addr, size, assume_locks] {
        ReadMemory(device_addr, size, true, assume_locks);
    });
    // A CPU overwrite or unmap ends any read watch: relaxed keeps them for allowlisted outputs.
    if (EmulatorSettings.GetReadbacksMode() == GpuReadbacksMode::Selective ||
        EmulatorSettings.GetReadbacksMode() == GpuReadbacksMode::Relaxed) {
        memory_tracker->WatchReads(device_addr, size, false);
    }
}

// the game fills its per-frame buffers (constants, skinning output) sequentially and
// every 4 KiB page cost a protection fault (~110k/s in the test scene, a fifth of each
// render worker's time in the kernel). A fault unprotects the aligned window around it instead;
// pages marked CPU-modified without being written only cost an upload when bound.
// Item: context = BufferCache, source = guest address, destination = host pointer, size,
// extra = the Buffer whose mapping holds the destination (flushed after the copy).
void BufferCache::RunGuestCopy(const Ps4Copy::Item& item) {
    auto* cache = static_cast<BufferCache*>(item.context);
    auto* dst = reinterpret_cast<u8*>(item.destination);
    cache->memory->CopySparseMemory(item.source, dst, item.size);
    auto* buffer = reinterpret_cast<Buffer*>(item.extra);
    buffer->Flush(dst - buffer->mapped_data.data(), item.size);
}

// Small guest copies run on the recording thread (it spins for work: no wakeup, and it is
// idle most of the time); PoolSmallCopies (toggle 524288) batches them for the copy threads.
void BufferCache::SmallGuestCopy(const Ps4Copy::Item& item) {
    if (scheduler.IsRecordingDeferred() && !Ps4Toggle::Disabled(Ps4Toggle::PoolSmallCopies)) {
        scheduler.RecordHostCopy([item] { item.run(item); });
        return;
    }
    Ps4Copy::QueueCopy(item);
}

void BufferCache::ExtendWriteFault(VAddr device_addr) {
    static const u64 window = [] {
        const char* env = std::getenv("ORDER1886_FAULT_WINDOW");
        const u64 kib = env ? std::strtoull(env, nullptr, 10) : 256;
        return std::bit_ceil(std::clamp<u64>(kib, 4, 1024)) * 1024;
    }();
    if (window <= TRACKER_BYTES_PER_PAGE || Ps4Toggle::Disabled(Ps4Toggle::FaultWindow)) {
        return;
    }
    memory_tracker->ExtendWriteFault(Common::AlignDown(device_addr, window), window);
}

void BufferCache::ReadMemory(VAddr device_addr, u64 size, bool is_write, bool assume_locks) {
    // A CPU read of a watched output under the relaxed policy (the aim focus, see
    // ReadbackWatchedShader) returns at once with the value of the previous read; the bytes read
    // are copied from the GPU and reach guest memory when that copy completes. Waiting for them
    // (scheduler.Finish() three times a frame) corrupted skinned and cloth vertices in the
    // chapter II cutscene; no other bytes of the page are written back.
    if (!is_write && EmulatorSettings.GetReadbacksMode() == GpuReadbacksMode::Relaxed) {
        const VAddr page = Common::AlignDown(device_addr, TRACKER_BYTES_PER_PAGE);
        memory_tracker->WatchReads(
            page, Common::AlignUp(device_addr + size, TRACKER_BYTES_PER_PAGE) - page, false);
        const auto publish = [this, device_addr, size] {
            const auto* arena =
                GetArena(device_addr >> block_shift, (device_addr + size - 1) >> block_shift);
            const auto download =
                staging_pool.Request(size, VideoCore::MemoryType::HostCached, 0, true);
            const std::array copies{vk::BufferCopy{
                .srcOffset = device_addr - arena->cpu_addr,
                .dstOffset = download.offset,
                .size = size,
            }};
            runtime.CopyBuffer(arena, download.buffer, copies);
            scheduler.DeferOperation([this, device_addr, size, download] {
                download.buffer->Invalidate(download.offset, size);
                memory->TryWriteBacking(std::bit_cast<u8*>(device_addr), download.mapped, size);
                staging_pool.FreeDeferred(download);
            });
        };
        if (assume_locks) {
            publish();
        } else {
            liverpool->SendCommand<false>(publish);
        }
        return;
    }
    const auto flush_request = [this, device_addr, size, is_write] {
        const u32 first_block = device_addr >> block_shift;
        const u32 last_block = (device_addr + size - 1) >> block_shift;
        const auto* arena = GetArena(first_block, last_block);

        // GPU-modified ranges come as many small scattered islands,
        // so the download is widened to a window around the request
        constexpr u64 WindowSize = 512_KB;
        const VAddr arena_end = arena->cpu_addr + arena->size_bytes;
        const VAddr window_start =
            std::max<VAddr>(Common::AlignDown(device_addr, WindowSize), arena->cpu_addr);
        const VAddr window_end = std::min<VAddr>(
            std::max<VAddr>(window_start + WindowSize, device_addr + size), arena_end);
        if (is_write && deferred_readbacks_enabled &&
            !Ps4Toggle::Disabled(Ps4Toggle::DeferredReadbacks)) {
            bool on_gpu;
            {
                std::scoped_lock lock{gpu_ranges_mutex};
                on_gpu = gpu_modified_ranges.Intersects(device_addr, size);
            }
            if (!on_gpu && DeferReadback(arena, window_start, window_end - window_start)) {
                memory_tracker->MarkRegionAsCpuModified(device_addr, size);
                return;
            }
        }
        // GPU data of earlier deferred readbacks in this window must reach guest memory
        // before this readback completes.
        WaitDeferredReadbacks(window_start, window_end - window_start);
        DownloadMemory(arena, window_start, window_end - window_start);
        if (is_write) {
            memory_tracker->MarkRegionAsCpuModified(device_addr, size);
        }
    };
    if (assume_locks) {
        flush_request();
    } else {
        liverpool->SendCommand<true>(std::move(flush_request));
    }
}

void BufferCache::DownloadMemory(const Buffer* arena, VAddr device_addr, u64 size) {
    boost::container::small_vector<vk::BufferCopy, 1> copies;
    u64 total_size_bytes = 0;
    const VAddr arena_base = arena->cpu_addr;
    memory_tracker->ForEachDownloadRange<false>(device_addr, size, [&](u64 address, u64 size) {
        const auto add_download = [&](VAddr start, VAddr end) {
            const u64 new_offset = start - arena_base;
            const u64 new_size = end - start;
            copies.push_back(vk::BufferCopy{
                .srcOffset = new_offset,
                .dstOffset = total_size_bytes,
                .size = new_size,
            });
            // Align up to avoid cache conflicts
            constexpr u64 align = 64ULL;
            constexpr u64 mask = ~(align - 1ULL);
            total_size_bytes += (new_size + align - 1) & mask;
        };
        std::scoped_lock lock{gpu_ranges_mutex};
        gpu_modified_ranges.ForEachInRange(address, size, add_download);
        gpu_modified_ranges.Subtract(address, size);
    });
    if (total_size_bytes == 0) {
        return;
    }
    const auto download = staging_pool.Request(total_size_bytes, VideoCore::MemoryType::HostCached);
    for (auto& copy : copies) {
        copy.dstOffset += download.offset;
    }
    runtime.CopyBuffer(arena, download.buffer, copies);
    scheduler.Finish();

    download.buffer->Invalidate(download.offset, download.size);
    for (const auto& copy : copies) {
        auto* dst_addr = std::bit_cast<u8*>(arena_base + copy.srcOffset);
        memory->TryWriteBacking(dst_addr, download.mapped + (copy.dstOffset - download.offset),
                                copy.size);
    }
    memory_tracker->UnmarkRegionAsGpuModified(device_addr, size);
}

bool BufferCache::DeferReadback(const Buffer* arena, VAddr device_addr, u64 size) {
    std::vector<std::pair<VAddr, u64>> pages;
    memory_tracker->ForEachDownloadRange<false>(
        device_addr, size, [&](u64 address, u64 range) { pages.emplace_back(address, range); });
    std::vector<std::pair<VAddr, u64>> parts;
    u64 total = 0, snapshot_size = 0;
    {
        std::scoped_lock lock{gpu_ranges_mutex};
        for (const auto& [address, range] : pages) {
            gpu_modified_ranges.ForEachInRange(address, range, [&](VAddr start, VAddr end) {
                parts.emplace_back(start, end - start);
                total += Common::AlignUp(end - start, 64);
                snapshot_size += end - start;
            });
        }
        // Big readbacks (rare, tens of MiB) keep the waiting path: no snapshot that size.
        constexpr u64 MaxDeferredBytes = 4_MB;
        if (total > MaxDeferredBytes) {
            return false;
        }
        for (const auto& [address, range] : pages) {
            gpu_modified_ranges.Subtract(address, range);
        }
    }
    if (total == 0) {
        memory_tracker->UnmarkRegionAsGpuModified(device_addr, size);
        return true;
    }
    DeferredBatch batch{};
    batch.staging = staging_pool.Request(total, MemoryType::HostCached, 0, true);
    batch.snapshot.resize(snapshot_size);
    std::vector<vk::BufferCopy> copies;
    u64 offset = 0, snapshot_offset = 0;
    for (const auto& [addr, part] : parts) {
        copies.push_back(vk::BufferCopy{
            .srcOffset = addr - arena->cpu_addr,
            .dstOffset = batch.staging.offset + offset,
            .size = part,
        });
        memory->CopySparseMemory(addr, batch.snapshot.data() + snapshot_offset, part);
        batch.items.push_back({addr, part, offset, snapshot_offset});
        offset += Common::AlignUp(part, 64);
        snapshot_offset += part;
    }
    runtime.CopyBuffer(arena, batch.staging.buffer, copies);
    batch.tick = scheduler.CurrentTick(); // signalled by the flush that ends this submission
    {
        // Pending before the pages stop being GPU-modified: no upload in between takes them.
        std::scoped_lock lock{deferred_mutex};
        for (const auto& item : batch.items) {
            pending_readbacks.Add(item.addr, item.size);
        }
        deferred_readbacks.push_back(std::move(batch));
        has_pending_readbacks.store(true, std::memory_order_relaxed);
    }
    memory_tracker->UnmarkRegionAsGpuModified(device_addr, size);
    return true;
}

void BufferCache::ApplyDeferredReadbacks() {
    // Ranges whose guest bytes changed before the GPU data arrived: uploaded again from guest
    // memory (now merged), outside deferred_mutex (the tracker lock is taken under it in
    // SynchronizeMemory).
    std::vector<std::pair<VAddr, u64>> reupload;
    {
        std::scoped_lock lock{deferred_mutex};
        bool applied = false;
        while (!deferred_readbacks.empty() && scheduler.IsFree(deferred_readbacks.front().tick)) {
            DeferredBatch batch = std::move(deferred_readbacks.front());
            deferred_readbacks.pop_front();
            applied = true;
            batch.staging.buffer->Invalidate(batch.staging.offset, batch.staging.size);
            // GPU data goes where the guest left its bytes as they were at the fault.
            ApplyDeferredBatch(
                batch, deferred_readbacks,
                [&](const DeferredItem& item) { return batch.staging.mapped + item.staging_offset; },
                [&](VAddr addr, u8* dst, u64 size) { memory->CopySparseMemory(addr, dst, size); },
                [&](VAddr addr, const u8* src, u64 size) {
                    memory->TryWriteBacking(reinterpret_cast<void*>(addr), src, size);
                },
                [&](const DeferredItem& item, u64 changed) {
                    if (!changed) {
                        return;
                    }
                    std::scoped_lock ranges{gpu_ranges_mutex};
                    if (!gpu_modified_ranges.Intersects(item.addr, item.size)) {
                        reupload.emplace_back(item.addr, item.size);
                    }
                });
            staging_pool.FreeDeferred(batch.staging);
        }
        if (applied) {
            pending_readbacks.Clear();
            for (const auto& batch : deferred_readbacks) {
                for (const auto& item : batch.items) {
                    pending_readbacks.Add(item.addr, item.size);
                }
            }
            has_pending_readbacks.store(!deferred_readbacks.empty(), std::memory_order_relaxed);
        }
    }
    for (const auto& [addr, size] : reupload) {
        memory_tracker->MarkRegionAsCpuModified(addr, size);
    }
}

void BufferCache::WaitDeferredReadbacks(VAddr addr, u64 size) {
    if (!has_pending_readbacks.load(std::memory_order_relaxed)) {
        return;
    }
    u64 needed = 0;
    {
        std::scoped_lock lock{deferred_mutex};
        for (const auto& batch : deferred_readbacks) {
            for (const auto& item : batch.items) {
                if (addr < item.addr + item.size && item.addr < addr + size) {
                    needed = std::max(needed, batch.tick);
                }
            }
        }
    }
    if (!needed) {
        return;
    }
    if (!scheduler.IsFree(needed)) {
        if (needed >= scheduler.CurrentTick()) {
            scheduler.Finish(); // still being recorded
        } else {
            scheduler.Wait(needed);
        }
    }
    ApplyDeferredReadbacks();
}

bool BufferCache::PendingReadback(VAddr addr, u64 size) {
    if (!has_pending_readbacks.load(std::memory_order_relaxed)) {
        return false;
    }
    std::scoped_lock lock{deferred_mutex};
    return pending_readbacks.Intersects(addr, size);
}

namespace {
// ORDER1886_BUFFER_STATS=1 — how buffer bindings reach the GPU, by guest region (256 MiB),
// printed every 5 s: small read-only copies into the stream buffer, arena bindings, and the
// bytes those re-upload after CPU writes. Input for engine-level short paths.
struct BufferStats {
    struct Region {
        u64 stream_count{}, stream_bytes{}, arena_count{}, arena_bytes{}, upload_bytes{};
    };
    std::map<u64, Region> regions;
    /// Hot window: frame of the last binding per 64 KiB block, and the distribution of the
    /// frames between uses (1, 2, 3, 4, 5-8, 9-16, 17+): the ring's reuse distance.
    std::unordered_map<u64, u64> last_use;
    std::array<u64, 7> reuse{};
    std::chrono::steady_clock::time_point window = std::chrono::steady_clock::now();
    u64 calls = 0;
};
/// 256 MiB regions; 1 MiB inside the hot 0x104xxxxxxx window (the engine's frame data).
BufferStats& Stats();
void NoteHotUse(VAddr address, u32 size) {
    if ((address >> 28) != 0x104) {
        return;
    }
    auto& st = Stats();
    const u64 frame = Ps4Stats::gpu_frames.load(std::memory_order_relaxed);
    for (u64 block = address >> 16; block <= (address + size - 1) >> 16; ++block) {
        auto [it, inserted] = st.last_use.try_emplace(block, frame);
        if (!inserted && it->second != frame) {
            const u64 d = frame - it->second;
            ++st.reuse[d <= 4 ? d - 1 : d <= 8 ? 4 : d <= 16 ? 5 : 6];
            it->second = frame;
        }
    }
}
u64 RegionKey(VAddr address) {
    return (address >> 28) == 0x104 ? (address >> 20) | (1ull << 40) : address >> 28;
}
bool BufferStatsEnabled() {
    static const bool enabled = [] {
        const char* value = std::getenv("ORDER1886_BUFFER_STATS");
        return value && value[0] == '1';
    }();
    return enabled;
}
BufferStats& Stats() {
    static BufferStats stats;
    return stats;
}
void PrintBufferStats() {
    auto& st = Stats();
    if ((++st.calls & 4095) != 0) {
        return;
    }
    const auto now = std::chrono::steady_clock::now();
    const double seconds = std::chrono::duration<double>(now - st.window).count();
    if (seconds < 5.0) {
        return;
    }
    std::printf("Buffer stats (%.1f s, per second): region, stream copies/bytes, arena bindings, "
                "re-uploaded bytes\n", seconds);
    std::printf("  hot window reuse distance in frames (1,2,3,4,5-8,9-16,17+): %llu %llu %llu %llu "
                "%llu %llu %llu\n",
                (unsigned long long)st.reuse[0], (unsigned long long)st.reuse[1],
                (unsigned long long)st.reuse[2], (unsigned long long)st.reuse[3],
                (unsigned long long)st.reuse[4], (unsigned long long)st.reuse[5],
                (unsigned long long)st.reuse[6]);
    st.reuse = {};
    for (const auto& [region, r] : st.regions) {
        const u64 base = (region >> 40) ? (region & ((1ull << 40) - 1)) << 20 : region << 28;
        if ((region >> 40) && r.stream_bytes + r.upload_bytes < 1e6 * seconds) {
            continue; // quiet MiB of the hot window
        }
        std::printf("  %#012llx: %8.0f copies %8.2f MB, %8.0f arena %8.2f MB bound, %8.2f MB uploads\n",
                    static_cast<unsigned long long>(base), r.stream_count / seconds,
                    r.stream_bytes / seconds / 1e6, r.arena_count / seconds,
                    r.arena_bytes / seconds / 1e6,
                    r.upload_bytes / seconds / 1e6);
    }
    st.regions.clear();
    st.window = now;
}
} // namespace

bool BufferCache::MaterializeHtile(const Buffer* arena, VAddr device_addr, u32 size) {
    // ORDER1886_HTILE=0 keeps the unqualified adaptation out of the launch path: the
    // metadata registry still tracks words, but no GPU-written buffer is replaced by
    // one, so reads fall through to the normal paths.
    if (!EmulatorSettings.HtileEnabled()) {
        return false;
    }
    // CPU invalidation must finish before its buffer readback can retire this GPU write.
    return texture_cache.WithHtileWord(device_addr, size, [&](u32 htile) {
        SynchronizeMemory(arena, device_addr, size, true, false);
        runtime.FillBuffer(arena, arena->Offset(device_addr), size, htile);
        if (size <= 64_KB && EmulatorSettings.GetReadbacksMode() == GpuReadbacksMode::Selective)
            memory_tracker->WatchReads(device_addr, size, true);
        {
            std::scoped_lock lock{gpu_ranges_mutex};
            gpu_modified_ranges.Add(device_addr, size);
        }
        static std::atomic<u32> reports{};
        if (reports.fetch_add(1, std::memory_order_relaxed) < 8)
            LOG_INFO(Render_Vulkan, "Materialized HTILE address={:#x} bytes={} word={:#x}",
                     device_addr, size, htile);
    });
}

std::pair<const Buffer*, u64> BufferCache::ObtainBuffer(VAddr device_addr, u32 size,
                                                        bool is_written, bool is_texel_buffer) {
    texture_cache.ResolveReadbacks(device_addr, size, true, ReadbackSource::BufferObtain);
    if (!is_written) {
        if (texture_cache.HtileReadValue(device_addr, size)) {
            const u64 first_block = device_addr >> block_shift;
            const u64 last_block = (device_addr + size - 1) >> block_shift;
            const auto* arena = GetArena(first_block, last_block);
            EnsureResident(arena, first_block, last_block);
            if (MaterializeHtile(arena, device_addr, size))
                return {arena, arena->Offset(device_addr)};
        }
    }
    const bool stats = BufferStatsEnabled();
    if (stats) {
        PrintBufferStats();
        NoteHotUse(device_addr, size);
    }
    // For read-only buffers use device local stream buffer to reduce renderpass breaks.
    if (!is_written && size <= STREAM_THRESHOLD && !IsRegionGpuModified(device_addr, size)) {
        if (stats) {
            auto& region = Stats().regions[RegionKey(device_addr)];
            ++region.stream_count;
            region.stream_bytes += size;
        }
        // the guest data is copied on a copy thread, started now; submission and
        // guest-visible fences wait for it (Scheduler::WaitHostCopies).
        if (!stream_buffer.mapped_data.empty() &&
            !Ps4Toggle::Disabled(Ps4Toggle::DeferredStreamCopies)) {
            if (const auto offset = stream_buffer.Reserve(size, instance.UniformMinAlignment())) {
                SmallGuestCopy({
                    .run = &RunGuestCopy,
                    .context = this,
                    .source = device_addr,
                    .destination = reinterpret_cast<u64>(stream_buffer.mapped_data.data() + *offset),
                    .size = size,
                    .extra = reinterpret_cast<u64>(static_cast<Buffer*>(&stream_buffer)),
                });
                return {&stream_buffer, *offset};
            }
        }
        const auto [data, offset] = stream_buffer.Map(size, instance.UniformMinAlignment());
        memory->CopySparseMemory(device_addr, data, size);
        stream_buffer.Commit();
        return {&stream_buffer, offset};
    }
    const u64 first_block = device_addr >> block_shift;
    const u64 last_block = (device_addr + size - 1) >> block_shift;
    const auto* arena = GetArena(first_block, last_block);
    EnsureResident(arena, first_block, last_block);
    const u64 uploaded_before = Ps4Stats::buffer_upload_bytes.load(std::memory_order_relaxed);
    SynchronizeMemory(arena, device_addr, size, is_written, is_texel_buffer);
    if (is_written && size <= 64_KB && ReadbackLog()) {
        std::scoped_lock lock{writers_mutex};
        writers[device_addr] = {size, current_dispatch};
    }
    if (is_written && size <= 64_KB &&
        (EmulatorSettings.GetReadbacksMode() == GpuReadbacksMode::Selective ||
         (watch_written_buffers &&
          EmulatorSettings.GetReadbacksMode() == GpuReadbacksMode::Relaxed))) {
        memory_tracker->WatchReads(device_addr, size, true);
    }
    if (stats) {
        auto& region = Stats().regions[RegionKey(device_addr)];
        ++region.arena_count;
        region.arena_bytes += size;
        region.upload_bytes +=
            Ps4Stats::buffer_upload_bytes.load(std::memory_order_relaxed) - uploaded_before;
    }
    if (is_written) {
        texture_cache.NoteMetaShaderWrite(device_addr, size);
        std::scoped_lock lock{gpu_ranges_mutex};
        gpu_modified_ranges.Add(device_addr, size);
    }
    return {arena, arena->Offset(device_addr)};
}

std::pair<const Buffer*, u64> BufferCache::ObtainBufferForImage(VAddr device_addr, u32 size) {
    texture_cache.ResolveReadbacks(device_addr, size, true, ReadbackSource::BufferForImage);
    if (IsRegionGpuModified(device_addr, size)) {
        return ObtainBuffer(device_addr, size, false);
    }
    const auto staging = staging_pool.Request(size, VideoCore::MemoryType::HostUncached,
                                              instance.StorageMinAlignment());
    if (!Ps4Toggle::Disabled(Ps4Toggle::DeferredUploads)) {
        // texture data is copied on the copy threads (streaming: 100+ MB per frame);
        // the upload reads the staging only after submission, which waits for the copies.
        constexpr u64 Chunk = 1_MB;
        for (u64 offset = 0; offset < staging.size; offset += Chunk) {
            const Ps4Copy::Item item{
                .run = &RunGuestCopy,
                .context = this,
                .source = device_addr + offset,
                .destination = reinterpret_cast<u64>(staging.mapped + offset),
                .size = std::min(Chunk, staging.size - offset),
                .extra = reinterpret_cast<u64>(staging.buffer),
            };
            if (staging.size < Chunk) {
                SmallGuestCopy(item);
            } else {
                Ps4Copy::Async([item] { item.run(item); });
            }
        }
        return {staging.buffer, staging.offset};
    }
    memory->CopySparseMemory(device_addr, staging.mapped, staging.size);
    staging.Flush();
    return {staging.buffer, staging.offset};
}

bool BufferCache::IsRegionCpuModified(VAddr addr, size_t size) {
    return memory_tracker->IsRegionCpuModified(addr, size);
}

bool BufferCache::IsRegionGpuModified(VAddr addr, size_t size) {
    // Bytes of a deferred readback are only up to date in the arena.
    return memory_tracker->IsRegionGpuModified(addr, size) || PendingReadback(addr, size);
}

void BufferCache::ProcessFaultBuffer() {
    fault_manager->ProcessFaultBuffer();
}

void BufferCache::SynchronizeDmaBuffers() {
    for (const auto& range : resident_ranges) {
        const u64 page = range.start >> (arena_page_bits - block_shift);
        const VAddr device_addr = range.start << block_shift;
        const u64 size = (range.end - range.start) << block_shift;
        SynchronizeMemory(address_space[page], device_addr, size, false, false);
    }
}

const Buffer* BufferCache::GetArena(u64 first_block, u64 last_block) {
    const u64 first_page = first_block >> blocks_per_arena_page_shift;
    const u64 last_page = last_block >> blocks_per_arena_page_shift;
    ASSERT_MSG(last_page - first_page <= 1,
               "Buffer request cannot span more than two VA arena pages");

    const auto* first_arena = address_space[first_page];
    const auto* last_arena = address_space[last_page];
    if (first_arena == last_arena) {
        if (!first_arena) {
            const u64 base_block = Common::AlignDownPow2<u64>(first_block, blocks_per_arena_page);
            const u64 num_pages = last_page - first_page + 1;
            const auto* new_arena =
                &arenas.emplace_back(instance, base_block << block_shift,
                                     num_pages << arena_page_bits, MemoryType::Sparse);
            address_space[first_page] = new_arena;
            address_space[last_page] = new_arena;
        }
        return address_space[first_page];
    }

    LOG_WARNING(Render, "Migrating arena");

    const u64 first_addr = first_arena ? first_arena->cpu_addr : (first_page << arena_page_bits);
    const u64 first_size = first_arena ? first_arena->size_bytes : arena_page_size;
    const u64 last_size = last_arena ? last_arena->size_bytes : arena_page_size;

    const u64 base_block = first_addr >> block_shift;
    const u64 total_size = first_size + last_size;
    const u64 end_block = (first_addr + total_size) >> block_shift;
    auto* new_arena = &arenas.emplace_back(instance, first_addr, total_size, MemoryType::Sparse);
    auto* bind = BindsForArena(new_arena);
    resident_ranges.ForEachInRange(base_block, end_block, [&](const Backing& backing) {
        const u64 start = std::max(base_block, backing.start);
        const u64 end = std::min(end_block, backing.end);
        bind->binds.push_back(vk::SparseMemoryBind{
            .resourceOffset = (start - base_block) << block_shift,
            .size = (end - start) << block_shift,
            .memory = backing.memory,
            .memoryOffset = backing.offset + ((start - backing.start) << block_shift),
        });
    });

    u64 base_page = first_addr >> arena_page_bits;
    for (u32 page = 0; page < (first_size >> arena_page_bits); ++page) {
        address_space[base_page + page] = new_arena;
    }
    base_page = last_page;
    for (u32 page = 0; page < (last_size >> arena_page_bits); ++page) {
        address_space[base_page + page] = new_arena;
    }
    return new_arena;
}

void BufferCache::EnsureResident(const Buffer* arena, u64 first_block, u64 last_block) {
    u32 resident_blocks{};
    IntervalList bind_ranges;
    resident_ranges.ForEachGap(first_block, last_block + 1, [&](u64 start, u64 end) {
        resident_blocks += end - start;
        bind_ranges.Add({start, end});
    });

    if (bind_ranges.Empty()) {
        return;
    }
    Ps4Stats::Timer timer{Ps4Stats::t_resident};

    const vk::MemoryAllocateInfo alloc_info = {
        .allocationSize = resident_blocks << block_shift,
        .memoryTypeIndex = arena_memory_type_index,
    };
    const auto device_memory = Vulkan::Check(instance.GetDevice().allocateMemory(alloc_info));

    boost::container::small_vector<vk::BufferCopy, 8> copies;
    const auto staging =
        staging_pool.Request(resident_blocks * sizeof(vk::DeviceAddress), MemoryType::HostUncached);

    u64 memory_offset{};
    ArenaBinds* binds = BindsForArena(arena);
    auto* bda_addrs = reinterpret_cast<vk::DeviceAddress*>(staging.mapped);
    u64 offset = staging.offset;
    for (const auto& range : bind_ranges) {
        Backing backing;
        backing.start = range.start;
        backing.end = range.end;
        backing.memory = device_memory;
        backing.offset = memory_offset;
        resident_ranges.Add(backing);

        LOG_INFO(Render, "Making range start={}, end={} resident", backing.start, backing.end);

        const auto& bind = binds->binds.emplace_back(vk::SparseMemoryBind{
            .resourceOffset = (range.start << block_shift) - arena->cpu_addr,
            .size = (range.end - range.start) << block_shift,
            .memory = device_memory,
            .memoryOffset = memory_offset,
        });
        memory_offset += bind.size;

        for (u32 block = 0; block < bind.size; block += block_size) {
            *(bda_addrs++) = arena->BufferDeviceAddress() + bind.resourceOffset + block;
        }
        const u64 copy_size = (backing.end - backing.start) * sizeof(vk::DeviceAddress);
        copies.emplace_back(offset, backing.start * sizeof(vk::DeviceAddress), copy_size);
        offset += copy_size;
    }

    staging.Flush();
    runtime.CopyBuffer(staging.buffer, bda_pagetable_buffer.get(), copies);
}

bool BufferCache::SynchronizeMemory(const Buffer* arena, VAddr device_addr, u32 size,
                                    bool is_written, bool is_texel_buffer) {
    boost::container::small_vector<vk::BufferCopy, 4> copies;
    size_t total_size_bytes{};
    const Buffer* src_buffer{};
    const auto add_copy = [&](u64 addr, u64 size) {
        copies.emplace_back(total_size_bytes, addr, size);
        total_size_bytes += size;
    };
    memory_tracker->ForEachUploadRange(
        device_addr, size, is_written,
        [&](u64 addr, u64 size) {
            // The guest's copy of deferred readback bytes is stale until it arrives; the arena
            // keeps them.
            if (!has_pending_readbacks.load(std::memory_order_relaxed)) {
                add_copy(addr, size);
                return;
            }
            std::scoped_lock lock{deferred_mutex};
            pending_readbacks.ForEachNotInRange(addr, size, add_copy);
            // Pending bytes the guest wrote after the fault are newer than the arena's GPU
            // data (ApplyDeferredReadbacks keeps these bytes in guest memory).
            ForEachRewrittenPending(
                deferred_readbacks, addr, size,
                [&](VAddr src, u8* dst, u64 n) { memory->CopySparseMemory(src, dst, n); },
                add_copy);
        },
        [&] { src_buffer = UploadCopies(arena, copies, total_size_bytes); });

    if (src_buffer) {
        runtime.CopyBuffer(src_buffer, arena, copies);
    }
    if (is_texel_buffer && !is_written) {
        return SynchronizeMemoryFromImage(arena, device_addr, size);
    }
    return false;
}

const Buffer* BufferCache::UploadCopies(const Buffer* arena, std::span<vk::BufferCopy> copies,
                                        size_t total_size_bytes) {
    if (copies.empty()) {
        return nullptr;
    }
    // Resolve before launching host copies: a copy-thread fault could deadlock submission.
    for (const auto& copy : copies) {
        texture_cache.ResolveReadbacks(copy.dstOffset, copy.size, true, ReadbackSource::BufferUpload);
    }
    Ps4Stats::buffer_upload_bytes.fetch_add(total_size_bytes, std::memory_order_relaxed);
    const auto staging = staging_pool.Request(total_size_bytes, MemoryType::HostUncached);
    // the guest memory is copied into staging on the copy threads, started now in
    // groups of about 1 MiB; submission and guest-visible fences wait for them
    // (Scheduler::WaitHostCopies).
    if (!Ps4Toggle::Disabled(Ps4Toggle::DeferredUploads) && total_size_bytes < 1_MB) {
        // Small uploads join the calling thread's batch.
        for (auto& copy : copies) {
            SmallGuestCopy({
                .run = &RunGuestCopy,
                .context = this,
                .source = copy.dstOffset,
                .destination = reinterpret_cast<u64>(staging.mapped + copy.srcOffset),
                .size = copy.size,
                .extra = reinterpret_cast<u64>(staging.buffer),
            });
            copy.srcOffset += staging.offset;
            copy.dstOffset -= arena->cpu_addr;
        }
        return staging.buffer;
    }
    if (!Ps4Toggle::Disabled(Ps4Toggle::DeferredUploads)) {
        struct HostCopy {
            VAddr source;
            u8* destination;
            u64 size;
        };
        using Group = boost::container::small_vector<HostCopy, 8>;
        auto group = std::make_shared<Group>();
        u64 group_bytes = 0;
        const auto launch = [&] {
            Ps4Copy::Async([group, memory = memory, staging] {
                for (const auto& copy : *group) {
                    memory->CopySparseMemory(copy.source, copy.destination, copy.size);
                }
                staging.Flush();
            });
        };
        for (auto& copy : copies) {
            group->push_back({copy.dstOffset, staging.mapped + copy.srcOffset, copy.size});
            group_bytes += copy.size;
            copy.srcOffset += staging.offset;
            copy.dstOffset -= arena->cpu_addr;
            if (group_bytes >= 1_MB) {
                launch();
                group = std::make_shared<Group>();
                group_bytes = 0;
            }
        }
        if (!group->empty()) {
            launch();
        }
        return staging.buffer;
    }
    const auto copy = [&](std::size_t i) {
        memory->CopySparseMemory(copies[i].dstOffset, staging.mapped + copies[i].srcOffset,
                                 copies[i].size);
    };
    if (total_size_bytes >= 2_MB && copies.size() > 1) {
        Ps4Copy::ParallelFor(copies.size(), copy);
    } else {
        for (std::size_t i = 0; i < copies.size(); ++i) {
            copy(i);
        }
    }
    for (auto& copy : copies) {
        copy.srcOffset += staging.offset;
        copy.dstOffset -= arena->cpu_addr;
    }
    staging.Flush();
    return staging.buffer;
}

bool BufferCache::SynchronizeMemoryFromImage(const Buffer* arena, VAddr device_addr, u32 size) {
    if (auto type = texture_cache.IsMeta(device_addr)) {
        if (*type == TextureCache::MetaType::HTile) {
            if (MaterializeHtile(arena, device_addr, size)) return true;
        } else {
            LOG_WARNING(Render_Vulkan, "Unhandled metadata type {}", magic_enum::enum_name(*type));
        }
    }
    // most texel buffers alias no image; remember misses until images change.
    const u64 generation = texture_cache.RegistryGeneration();
    auto& miss = image_miss_cache[((device_addr >> 6) ^ size * 0x9E3779B1u) % image_miss_cache.size()];
    if (miss.address == device_addr && miss.size == size && miss.generation == generation &&
        !Ps4Toggle::Disabled(Ps4Toggle::TextureBindingMemo)) {
        return false;
    }
    const ImageId image_id = texture_cache.FindImageFromRange(device_addr, size);
    if (!image_id) {
        miss = {device_addr, size, generation};
        return false;
    }
    // the lookups above only read what the texture binding helper leaves alone; the
    // copy below changes image state, so the helper finishes first.
    runtime.BeforeImageAccess();
    Image& image = texture_cache.GetImage(image_id);
    ASSERT_MSG(device_addr == image.info.guest_address,
               "Texel buffer aliases image subresources {:x} : {:x}", device_addr,
               image.info.guest_address);
    const u64 arena_offset = arena->Offset(device_addr);
    boost::container::small_vector<vk::BufferImageCopy, 8> buffer_copies;
    for (u32 mip = 0; mip < image.info.resources.levels; mip++) {
        const auto& mip_info = image.info.mips_layout[mip];
        const u32 width = std::max(image.info.size.width >> mip, 1u);
        const u32 height = std::max(image.info.size.height >> mip, 1u);
        const u32 depth = std::max(image.info.size.depth >> mip, 1u);
        if (arena_offset + mip_info.offset + mip_info.size > arena->size_bytes) {
            break;
        }
        buffer_copies.push_back(vk::BufferImageCopy{
            .bufferOffset = mip_info.offset,
            .bufferRowLength = mip_info.pitch,
            .bufferImageHeight = mip_info.height,
            .imageSubresource{
                .aspectMask = image.aspect_mask & ~vk::ImageAspectFlagBits::eStencil,
                .mipLevel = mip,
                .baseArrayLayer = 0,
                .layerCount = image.info.resources.layers,
            },
            .imageOffset = {0, 0, 0},
            .imageExtent = {width, height, depth},
        });
    }
    if (buffer_copies.empty()) {
        return false;
    }
    auto& tile_manager = texture_cache.GetTileManager();
    tile_manager.TileImage(image, buffer_copies, arena, arena_offset);
    return true;
}

void BufferCache::SubmitPendingArenaBinds(Vulkan::SubmitInfo& info) {
    if (pending_binds.empty()) {
        return;
    }

    std::vector<vk::SparseBufferMemoryBindInfo> buffer_binds;
    buffer_binds.reserve(pending_binds.size());

    for (const auto& binds : pending_binds) {
        buffer_binds.emplace_back(vk::SparseBufferMemoryBindInfo{
            .buffer = binds.arena->Handle(),
            .bindCount = static_cast<u32>(binds.binds.size()),
            .pBinds = binds.binds.data(),
        });
    }

    const u64 signal_tick = memory_semaphore.NextTick();
    const auto signal_sema = memory_semaphore.Handle();

    const vk::TimelineSemaphoreSubmitInfo timeline_si = {
        .signalSemaphoreValueCount = 1u,
        .pSignalSemaphoreValues = &signal_tick,
    };

    const vk::BindSparseInfo sparse_info = {
        .pNext = &timeline_si,
        .bufferBindCount = static_cast<u32>(buffer_binds.size()),
        .pBufferBinds = buffer_binds.data(),
        .signalSemaphoreCount = 1u,
        .pSignalSemaphores = &signal_sema,
    };

    info.AddWait(signal_sema, signal_tick);
    auto submit_result = instance.GetSparseQueue().bindSparse(sparse_info);
    ASSERT_MSG(submit_result != vk::Result::eErrorDeviceLost, "Device lost during submit");

    pending_binds.clear();
}

} // namespace VideoCore
