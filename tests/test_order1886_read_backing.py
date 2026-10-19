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

    def test_htile_buffer_materialization_tracks_cpu_access(self):
        text = (ROOT / 'gpu/shadps4/video_core/buffer_cache/buffer_cache.cpp').read_text(encoding='utf-8')
        begin = text.index('std::pair<const Buffer*, u64> BufferCache::ObtainBuffer(')
        prefix = text[begin:text.index('    const bool stats = BufferStatsEnabled();', begin)]
        header = (ROOT / 'gpu/shadps4/video_core/texture_cache/surface_metadata.h').as_posix()
        self.compile_and_run('#include "' + header + '"\n' + r'''
#include <array>
#include <atomic>
#include <cassert>
#include <cstring>
using u32=uint32_t; using u64=uint64_t; using VAddr=u64;
#define LOG_INFO(...) ((void)0)
constexpr u64 operator""_KB(unsigned long long value) { return value*1024; }
enum class ReadbackSource { BufferObtain };
enum class GpuReadbacksMode { Relaxed, Selective, Precise };
static struct { GpuReadbacksMode mode=GpuReadbacksMode::Selective;
    GpuReadbacksMode GetReadbacksMode() const { return mode; }
} EmulatorSettings;
struct Buffer { u64 Offset(u64 address) const { return address-0x1000; } };
class BufferCache {
public:
    Buffer arena;
    bool resident{}, synchronized{};
    unsigned fills{}, watches{};
    std::array<unsigned char,64> bytes{};
    struct Texture {
        VideoCore::SurfaceMetadata metadata;
        void ResolveReadbacks(u64,u32,bool,ReadbackSource) {}
        auto HtileReadValue(u64 a,u64 n) { return metadata.HtileWord(a,n); }
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
        ++owner->fills;
        for(unsigned i=0;i<n;i+=4) std::memcpy(owner->bytes.data()+offset+i,&word,4);
    }} runtime{this};
    static constexpr unsigned block_shift=6;
    const Buffer* GetArena(u64,u64) { return &arena; }
    void EnsureResident(const Buffer* a,u64,u64) { assert(a==&arena); resident=true; }
    bool SynchronizeMemory(const Buffer* a,u64 address,u32 size,bool written,bool texel) {
        assert(a==&arena && resident && address==0x1000 && size==16 && written && !texel);
        synchronized=true; return true;
    }
    std::pair<const Buffer*,u64> ObtainBuffer(VAddr,u32,bool,bool=false);
};
''' + prefix + r'''
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
    }
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
