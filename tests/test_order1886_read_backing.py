"""Host copies must bypass guest read protection without losing sparse semantics."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReadBackingTests(unittest.TestCase):
    def compile_and_run(self, source, cxx=False):
        environment = os.environ.copy()
        compiler = shutil.which(environment.get('CXX' if cxx else 'CC', 'clang++' if cxx else 'clang'))
        if not compiler and os.name == 'nt':
            compiler = str(Path(environment.get('MSYS2_ROOT', r'C:\msys64')) /
                           'clang64/bin' / ('clang++.exe' if cxx else 'clang.exe'))
        self.assertIsNotNone(compiler)
        environment['PATH'] = str(Path(compiler).parent) + os.pathsep + environment.get('PATH', '')
        with tempfile.TemporaryDirectory(prefix='order-backing-') as temporary:
            directory = Path(temporary)
            exe = directory / ('read.exe' if os.name == 'nt' else 'read')
            if isinstance(source, str):
                source_path = directory / 'shim.cpp'
                source_path.write_text(source, encoding='utf-8')
            else:
                source_path = source
            command = [compiler, '-std=c++23' if cxx else '-std=c11', '-O2', '-UNDEBUG',
                       '-Wall', '-Wextra', '-Werror', '-pthread', '-I' + str(ROOT / 'src'), str(source_path)]
            if os.name == 'nt' and not cxx:
                command += [str(ROOT / 'src/compat_win.c'), '-lonecore', '-lws2_32',
                            '-Wl,--disable-high-entropy-va']
            result = subprocess.run(command + ['-o', str(exe)], env=environment,
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], env=environment, capture_output=True,
                                    text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_sparse_protected_reads_and_mapping_lifetime(self):
        self.compile_and_run(ROOT / 'tests/test_memory_read_backing.c')

    def test_gpu_ownership_retires_before_mapping_replacement(self):
        self.compile_and_run(ROOT / 'tests/test_memory_ownership.c')

    def test_htile_metadata_preserves_shader_writes_and_ownership(self):
        self.compile_and_run(ROOT / 'tests/test_htile_metadata.cpp', cxx=True)

    def test_htile_unsupported_clear_executes_original_shader(self):
        from test_order1886_srt_codegen import function_body
        text = (ROOT / 'gpu/shadps4/video_core/renderer_vulkan/vk_rasterizer.cpp').read_text(encoding='utf-8')
        recognizer = function_body(text, 'bool Rasterizer::IsComputeMetaClear(')
        header = (ROOT / 'gpu/shadps4/video_core/texture_cache/surface_metadata.h').as_posix()
        self.compile_and_run('#include "' + header + '"\n' + r'''
#include <array>
#include <cassert>
#include <vector>
using u32=uint32_t; using u64=uint64_t; using VAddr=u64;
#define LOG_TRACE(...) ((void)0)
namespace Shader { enum class SwStage { Compute }; }
// The runtime gate reads ORDER1886_HTILE and is off by default; this fixture models
// a player who opted in, which is the path the recognizer asserts.
static struct { bool HtileEnabled() const { return true; } } EmulatorSettings;
struct Sharp { u64 base_address=0x1000, size=16; u64 GetSize() const { return size; } };
struct Info;
struct Desc { bool is_written=true; Sharp sharp; bool IsSpecial() const { return false; }
    Sharp GetSharp(const Info&) const { return sharp; } };
struct Info { std::vector<Desc> buffers{Desc{}}; bool has_bitwise_xor=false; };
struct Pipeline { Info info; bool IsCompute() const { return true; }
    const Info& GetStage(Shader::SwStage) const { return info; } };
struct Texture {
    VideoCore::SurfaceMetadata metadata;
    auto IsMeta(u64 address) { return metadata.TypeAt(address); }
    bool ClearMeta(u64 address,u64 size) { return metadata.Clear(address,size); }
    auto HtileReadExtent(u64 address) { return metadata.HtileExtent(address); }
};
struct Rasterizer {
    Texture texture_cache;
    struct Memory { u64 maximum=UINT64_MAX;
        u64 ClampRangeSize(u64,u64 n) { return n<maximum ? n : maximum; }
    } vm;
    Memory* memory=&vm;
    struct BufferCache { Texture* texture; unsigned fills{};
        auto ObtainBuffer(u64 address,u32 size,bool written) {
            assert(!written && texture->metadata.HtileWord(address,size));
            ++fills; return std::pair{true,0};
        }
    } buffer_cache{&texture_cache};
    bool IsComputeMetaClear(const Pipeline*);
};
''' + recognizer + r'''
int main() {
    using Type=VideoCore::SurfaceMetadata::Type;
    for(u32 layers:{0u,2u,32u,33u}) {
        Rasterizer rasterizer; Pipeline pipeline;
        rasterizer.texture_cache.metadata.Register(0x1000,1,Type::HTile,~0u,layers);
        std::array<u32,4> real_bytes{};
        assert(!rasterizer.IsComputeMetaClear(&pipeline));
        // Original clear dispatch executes, then a real per-slice write changes its bytes.
        real_bytes.fill(0x12340000u); real_bytes[0]=0xface;
        rasterizer.texture_cache.metadata.Touch(0x1000,0,false);
        assert(!rasterizer.texture_cache.metadata.HtileWord(0x1000,16));
        assert(rasterizer.buffer_cache.fills==0 && real_bytes[0]==0xface);
    }
    Rasterizer oversized; Pipeline large;
    oversized.texture_cache.metadata.Register(0x1000,1,Type::HTile);
    large.info.buffers[0].sharp.size=u64{1}<<32;
    assert(!oversized.IsComputeMetaClear(&large) && !oversized.buffer_cache.fills);
    Rasterizer unmapped; Pipeline partial;
    unmapped.texture_cache.metadata.Register(0x1000,1,Type::HTile);
    unmapped.vm.maximum=8;
    assert(!unmapped.IsComputeMetaClear(&partial) && !unmapped.buffer_cache.fills);
    for(bool unsupported_first:{false,true}) {
        Rasterizer mixed; Pipeline multiple;
        mixed.texture_cache.metadata.Register(0x1000,1,Type::HTile,~0u,33);
        mixed.texture_cache.metadata.Register(0x2000,2,Type::CMask);
        Desc unsupported, color; color.sharp.base_address=0x2000;
        multiple.info.buffers=unsupported_first ? std::vector<Desc>{unsupported,color}
                                              : std::vector<Desc>{color,unsupported};
        assert(!mixed.IsComputeMetaClear(&multiple));
        assert(!mixed.buffer_cache.fills);
    }
    Rasterizer supported; Pipeline small;
    supported.texture_cache.metadata.Register(0x1000,1,Type::HTile);
    assert(supported.IsComputeMetaClear(&small) && supported.buffer_cache.fills==1);
}
''', cxx=True)

    def test_htile_buffer_materialization_tracks_cpu_access(self):
        from test_order1886_srt_codegen import function_body
        text = (ROOT / 'gpu/shadps4/video_core/buffer_cache/buffer_cache.cpp').read_text(encoding='utf-8')
        materialize = function_body(text, 'bool BufferCache::MaterializeHtile(')
        begin = text.index('std::pair<const Buffer*, u64> BufferCache::ObtainBuffer(')
        prefix = text[begin:text.index('    const bool stats = BufferStatsEnabled();', begin)]
        header = (ROOT / 'gpu/shadps4/video_core/texture_cache/surface_metadata.h').as_posix()
        self.compile_and_run('#include "' + header + '"\n' + r'''
#include <array>
#include <atomic>
#include <cassert>
#include <cstring>
#include <functional>
#include <future>
#include <thread>
using u32=uint32_t; using u64=uint64_t; using VAddr=u64;
#define LOG_INFO(...) ((void)0)
constexpr u64 operator""_KB(unsigned long long value) { return value*1024; }
enum class ReadbackSource { BufferObtain };
enum class GpuReadbacksMode { Relaxed, Selective, Precise };
static struct { GpuReadbacksMode mode=GpuReadbacksMode::Selective;
    GpuReadbacksMode GetReadbacksMode() const { return mode; }
    // The HTILE gate defaults off in the runtime; this fixture models the opted-in
    // player so the materialization path it asserts stays exercised.
    bool HtileEnabled() const { return htile; }
    bool htile=true;
} EmulatorSettings;
struct Buffer { u64 Offset(u64 address) const { return address-0x1000; } };
class BufferCache {
public:
    Buffer arena;
    bool resident{}, synchronized{};
    unsigned fills{}, watches{};
    std::array<unsigned char,64> bytes{};
    std::function<void()> before_fill;
    bool race_during_fill{}, cpu_retired{};
    std::promise<void> cpu_entered, cpu_done;
    std::thread cpu;
    struct Texture {
        VideoCore::SurfaceMetadata metadata;
        void ResolveReadbacks(u64,u32,bool,ReadbackSource) {}
        auto HtileReadValue(u64 a,u64 n) { return metadata.HtileWord(a,n); }
        bool WithHtileWord(u64 a,u64 n,auto&& use) { return metadata.WithHtileWord(a,n,use); }
    } texture_cache;
    struct Tracker { unsigned calls{}; void WatchReads(u64 a,u64 n,bool enabled) {
        assert(a==0x1000 && n==16 && enabled); ++calls;
    }} tracker;
    Tracker* memory_tracker=&tracker;
    struct Ranges { unsigned calls{}; void Add(u64 a,u64 n) {
        assert(a==0x1000 && n==16); ++calls;
    }} gpu_modified_ranges;
    std::mutex gpu_ranges_mutex;
    struct Runtime { BufferCache* owner; void FillBuffer(const Buffer* arena,u64 offset,u32 n,u32 word) {
        assert(arena==&owner->arena && owner->resident && owner->synchronized);
        assert(n==16 && offset==0);
        if(owner->race_during_fill) {
            owner->cpu=std::thread([owner=owner] {
                owner->cpu_entered.set_value();
                owner->texture_cache.metadata.Write(0x1000,16);
                // Actual CPU invalidation now reaches buffer retirement only after metadata.
                assert(owner->gpu_modified_ranges.calls==1);
                owner->cpu_retired=true; owner->bytes.fill(0x77);
                owner->cpu_done.set_value();
            });
            owner->cpu_entered.get_future().wait();
            assert(owner->cpu_done.get_future().wait_for(std::chrono::milliseconds(50))==
                   std::future_status::timeout);
        }
        ++owner->fills;
        for(unsigned i=0;i<n;i+=4) std::memcpy(owner->bytes.data()+offset+i,&word,4);
    }} runtime{this};
    static constexpr unsigned block_shift=6;
    const Buffer* GetArena(u64,u64) { return &arena; }
    void EnsureResident(const Buffer* a,u64,u64) {
        assert(a==&arena); resident=true;
        if(before_fill) before_fill();
    }
    bool SynchronizeMemory(const Buffer* a,u64 address,u32 size,bool written,bool texel) {
        assert(a==&arena && resident && address==0x1000 && size==16 && written && !texel);
        synchronized=true; return true;
    }
    std::pair<const Buffer*,u64> ObtainBuffer(VAddr,u32,bool,bool=false);
    bool MaterializeHtile(const Buffer*,VAddr,u32);
};
''' + materialize + '\n' + prefix + r'''
    (void)is_texel_buffer;
    return {nullptr,0};
}
int main() {
    for(auto mode:{GpuReadbacksMode::Relaxed,GpuReadbacksMode::Selective,GpuReadbacksMode::Precise}) {
        EmulatorSettings.mode=mode;
        BufferCache cache;
        cache.bytes.fill(0x55);
        cache.texture_cache.metadata.Register(0x1000,1,VideoCore::SurfaceMetadata::Type::HTile);
        cache.texture_cache.metadata.Clear(0x1000,16);
        const auto [buffer,offset]=cache.ObtainBuffer(0x1000,16,false);
        assert(buffer==&cache.arena && !offset && cache.fills==1);
        assert(cache.gpu_modified_ranges.calls==1);
        assert(cache.tracker.calls==(mode==GpuReadbacksMode::Selective ? 1u : 0u));
        u32 word{}; std::memcpy(&word,cache.bytes.data(),4); assert(word==0xfffc0000u);
        for(unsigned i=16;i<cache.bytes.size();++i) assert(cache.bytes[i]==0x55);
        cache.texture_cache.metadata.Write(0x1004,4);
        assert(!cache.ObtainBuffer(0x1000,16,false).first && cache.fills==1);
        assert(!cache.ObtainBuffer(0x1000,16,true).first && cache.fills==1);
        cache.texture_cache.metadata.Clear(0x1000,16);
        cache.before_fill=[&] {
            cache.texture_cache.metadata.Write(0x1000,16);
            cache.bytes.fill(0x77);
        };
        assert(!cache.ObtainBuffer(0x1000,16,false).first && cache.fills==1);
        for(auto value:cache.bytes) assert(value==0x77);
    }
    BufferCache racing;
    racing.texture_cache.metadata.Register(0x1000,1,VideoCore::SurfaceMetadata::Type::HTile);
    racing.texture_cache.metadata.Clear(0x1000,16);
    racing.race_during_fill=true;
    assert(racing.ObtainBuffer(0x1000,16,false).first);
    racing.cpu.join();
    assert(racing.cpu_retired && racing.fills==1);
    for(auto value:racing.bytes) assert(value==0x77);
}
''', cxx=True)

    def test_cpu_write_invalidates_metadata_before_buffer_readback(self):
        from test_order1886_srt_codegen import function_body
        text = (ROOT / 'gpu/shadps4/video_core/renderer_vulkan/vk_rasterizer.cpp').read_text(encoding='utf-8')
        invalidate = function_body(text, 'bool Rasterizer::InvalidateMemory(')
        header = (ROOT / 'gpu/shadps4/video_core/texture_cache/surface_metadata.h').as_posix()
        self.compile_and_run('#include "' + header + '"\n' + r'''
#include <cassert>
using u64=uint64_t; using VAddr=u64;
namespace VideoCore { enum class ReadbackSource { CpuWrite }; }
struct Rasterizer {
    struct Texture {
        VideoCore::SurfaceMetadata metadata;
        void NoteMetaShaderWrite(u64 a,u64 n) { metadata.Write(a,n); }
        void ResolveReadbacks(u64 a,u64 n,bool,VideoCore::ReadbackSource) {
            assert(!metadata.HtileWord(a,n));
        }
        void InvalidateMemory(u64 a,u64 n) { metadata.Write(a,n); }
    } texture_cache;
    struct Buffer { Texture* texture; unsigned calls{};
        void InvalidateMemory(u64 a,u64 n,bool) {
            assert(!texture->metadata.HtileWord(a,n)); ++calls;
        }
    } buffer_cache{&texture_cache};
    void DrainDrawPipe() {}
    bool IsMapped(u64,u64) { return true; }
    bool InvalidateMemory(u64,u64,bool=false);
};
''' + invalidate + r'''
int main() {
    Rasterizer rasterizer;
    rasterizer.texture_cache.metadata.Register(0x1000,1,VideoCore::SurfaceMetadata::Type::HTile);
    assert(rasterizer.texture_cache.metadata.Clear(0x1000,16));
    assert(rasterizer.InvalidateMemory(0x1000,16));
    assert(rasterizer.buffer_cache.calls==1);
}
''', cxx=True)

    def test_protected_memory_api_outputs_publish_outside_internal_locks(self):
        self.compile_and_run(ROOT / 'tests/test_memory_output_publication.c')

    def test_actual_upload_copy_uses_backing_interface(self):
        text = (ROOT / 'gpu/shim/ps4gpu.cpp').read_text(encoding='utf-8')
        copy = text[text.index('static void CopySparseSerial('):
                    text.index('void MemoryManager::CopySparseMemory(')]
        self.compile_and_run(r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstring>
using VAddr=uintptr_t; using u8=uint8_t; using u64=uint64_t;
static unsigned calls;
[[maybe_unused]] static int runtime_memory_region(uintptr_t address,uintptr_t *start,
                                                uintptr_t *end,int *mapped) {
    *start=address; *end=address+17; *mapped=1; return 1;
}
[[maybe_unused]] static void runtime_memory_read_backing(uintptr_t address,void *out,uint64_t size) {
    assert(address==0x12340000 && size==17);
    ++calls; std::memset(out,0x42,size);
}
''' + copy + r'''
int main() {
    u8 out[17]{};
    CopySparseSerial(0x12340000,out,sizeof(out));
    assert(calls==1);
    for (u8 value:out) assert(value==0x42);
}
''', cxx=True)


if __name__ == '__main__':
    unittest.main()
