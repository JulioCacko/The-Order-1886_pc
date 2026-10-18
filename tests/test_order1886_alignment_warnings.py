"""Repeated alignment warnings retain independent, cumulative diagnostics."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from tests.test_order1886_srt_codegen import function_body

ROOT = Path(__file__).resolve().parents[1]


class AlignmentWarningTests(unittest.TestCase):
    def test_real_counter_reports_first_and_exponential_repeats_per_shader_alignment(self):
        text = (ROOT / 'gpu/shadps4/video_core/renderer_vulkan/vk_rasterizer.cpp').read_text()
        signature = 'u64 Rasterizer::CountUnalignedWarning('
        self.assertIn(signature, text, 'Repeated alignment warnings are not yet counted')
        source = r'''
#include <bit>
#include <cassert>
#include <cstdint>
#include <map>
#include <utility>
#include <vector>
using u64=uint64_t; using u32=uint32_t;
class Rasterizer {
public:
    u64 CountUnalignedWarning(u64 shader, u32 alignment);
    std::map<std::pair<u64,u32>,u64> unaligned_warning_counts;
};
''' + function_body(text, signature) + r'''
int main() {
    Rasterizer renderer;
    std::vector<u64> emitted;
    for (u64 count=1; count<=8192; ++count) {
        auto report=renderer.CountUnalignedWarning(0x231d370b,1);
        if (report) emitted.push_back(report);
    }
    assert(emitted.size()==14);
    assert(emitted.front()==1 && emitted.back()==8192);
    for (unsigned i=1;i<emitted.size();++i) assert(emitted[i]==2*emitted[i-1]);
    assert(renderer.unaligned_warning_counts[std::make_pair(u64{0x231d370b},u32{1})]==8192);
    assert(renderer.CountUnalignedWarning(0x231d370b,2)==1);
    assert(renderer.CountUnalignedWarning(0xb938dd39,1)==1);
    assert(renderer.CountUnalignedWarning(0x231d370b,1)==0);
}
'''
        env = os.environ.copy()
        compiler = shutil.which(env.get('CXX', 'clang++'))
        candidate = Path(env.get('MSYS2_ROOT', r'C:\msys64')) / 'clang64/bin/clang++.exe'
        if os.name == 'nt' and compiler is None and candidate.is_file():
            compiler = str(candidate)
            env['PATH'] = str(candidate.parent) + os.pathsep + env.get('PATH', '')
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory(prefix='order-warning-count-') as temporary:
            cpp = Path(temporary) / 'test.cpp'
            exe = Path(temporary) / ('test.exe' if os.name == 'nt' else 'test')
            cpp.write_text(source)
            compiled = subprocess.run([compiler, '-std=c++23', '-UNDEBUG', str(cpp), '-o', str(exe)],
                                      capture_output=True, text=True, env=env)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
