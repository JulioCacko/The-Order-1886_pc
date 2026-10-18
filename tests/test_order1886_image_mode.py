"""CPU checks for the captured Chapter 2 compute texture's uniform mode guard."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OrderImageModeTests(unittest.TestCase):
    def test_inactive_mode_requires_exact_contract_bounds_and_coherent_read(self):
        header = ROOT / 'gpu/shadps4/video_core/renderer_vulkan/order1886_image_mode.h'
        self.assertTrue(header.is_file(), 'The proven compute image-mode guard is missing')
        source = r'''
#include <array>
#include <cassert>
#include <optional>
#include <span>
#include "video_core/renderer_vulkan/order1886_image_mode.h"
struct Fetch { unsigned load_mask{}; std::array<unsigned,8> offsets{}; };
struct Image {
    bool is_written{}, is_atomic{}, is_depth{}, is_r128{};
    unsigned declared_binding_count{1};
    Shader::SharpFetchPostOp post_op{Shader::SharpFetchPostOp::None};
    Shader::MipStorageFallbackMode mip_fallback_mode{Shader::MipStorageFallbackMode::None};
    Fetch sharp_fetch{255, {44,45,46,47,48,49,50,51}};
};
struct Sharp { u64 base_address{0x1060af6b08}; u64 size{1044480}; auto GetSize() const {return size;} };
struct Buffer {
    bool is_written{}, special{};
    Shader::BufferType buffer_type{Shader::BufferType::Guest};
    Shader::SharpFetchPostOp post_op{Shader::SharpFetchPostOp::None};
    Fetch sharp_fetch{15, {16,17,18,19}};
    Sharp sharp;
    bool IsSpecial() const {return special;}
    auto GetSharp(const auto&) const {return sharp;}
};
struct Info {
    u64 pgm_hash{0xa7b66f58};
    Shader::HwStage hw_stage{Shader::HwStage::Compute};
    std::array<Image,1> images;
    std::array<Buffer,2> buffers;
    std::array<u32,54> flat{};
    auto FlatUserData() const {return std::span{flat};}
};
int main() {
    Info stage;
    stage.flat[52] = 127;
    unsigned reads = 0;
    auto mode1 = [&](u64 address) -> std::optional<u32> {
        ++reads;
        assert(address == 0x1060af6b08ULL + 129740);
        return 1;
    };
    auto inactive = [&](const Info& info) {return Vulkan::IsOrderComputeImageInactive(info,0,mode1);};
    assert(inactive(stage) && reads == 1);
    auto snapshot_stage = stage;
    snapshot_stage.flat[52] = 0;
    snapshot_stage.buffers[1].sharp.size = 256;
    unsigned snapshot_reads = 0;
    // Bound snapshot mode3 must not be replaced using live mode1, even with clean flags.
    assert(!Vulkan::IsOrderComputeImageInactive(snapshot_stage,0,[&](u64) -> std::optional<u32> {
        ++snapshot_reads; return 1;
    }, true));
    assert(snapshot_reads == 0);
    assert(!Vulkan::IsOrderComputeImageInactive(stage,0,[](u64){return std::optional<u32>{3};}));
    // A GPU-dirty, CPU-dirty, or unmapped source is an unknown read, never inactivity.
    assert(!Vulkan::IsOrderComputeImageInactive(stage,0,[](u64){return std::optional<u32>{};}));
    reads = 0;
    assert(!Vulkan::IsOrderComputeImageInactive(stage,1,mode1));
    auto changed = stage; changed.pgm_hash ^= 1; assert(!inactive(changed));
    changed = stage; changed.hw_stage=Shader::HwStage::Fragment; assert(!inactive(changed));
    changed = stage; changed.images[0].is_written=true; assert(!inactive(changed));
    changed = stage; changed.images[0].is_r128=true; assert(!inactive(changed));
    changed = stage; changed.images[0].sharp_fetch.offsets[4]=44; assert(!inactive(changed));
    changed = stage; changed.images[0].declared_binding_count=0; assert(!inactive(changed));
    changed = stage; changed.buffers[1].is_written=true; assert(!inactive(changed));
    changed = stage; changed.buffers[1].special=true; assert(!inactive(changed));
    changed = stage; changed.buffers[1].buffer_type=Shader::BufferType::ReadConst; assert(!inactive(changed));
    changed = stage; changed.buffers[1].post_op=Shader::SharpFetchPostOp::ConvertCubeTo2DArray; assert(!inactive(changed));
    changed = stage; changed.buffers[1].sharp_fetch.offsets[0]=15; assert(!inactive(changed));
    changed = stage; changed.buffers[1].sharp.size=129743; assert(!inactive(changed));
    changed = stage; changed.buffers[1].sharp.base_address=~u64{0}-129741; assert(!inactive(changed));
    assert(reads == 0);
    changed = stage; changed.flat[52] = ~u32{0}; changed.buffers[1].sharp.base_address=0;
    changed.buffers[1].sharp.size = u64{1} << 32;
    assert(Vulkan::IsOrderComputeImageInactive(changed,0,[](u64 address) -> std::optional<u32> {
        assert(address==4294966476ULL); return 1;
    }));
}
'''
        env = os.environ.copy()
        compiler = shutil.which(env.get('CXX', 'clang++'))
        toolchain = Path(env.get('MSYS2_ROOT', r'C:\msys64')) / 'clang64'
        if os.name == 'nt' and compiler is None and (toolchain / 'bin/clang++.exe').is_file():
            compiler = str(toolchain / 'bin/clang++.exe')
            env['PATH'] = str(toolchain / 'bin') + os.pathsep + env.get('PATH', '')
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory(prefix='order-image-mode-') as temporary:
            cpp = Path(temporary) / 'test.cpp'
            exe = Path(temporary) / ('test.exe' if os.name == 'nt' else 'test')
            cpp.write_text(source)
            command = [compiler, '-std=c++23', '-UNDEBUG', '-DNOMINMAX',
                       '-I', str(ROOT / 'gpu/shim'), '-I', str(ROOT / 'gpu/shadps4'),
                       '-I', str(ROOT / 'gpu/third_party/magic_enum/include/magic_enum'),
                       str(cpp), '-o', str(exe)]
            compiled = subprocess.run(command, capture_output=True, text=True, env=env)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
