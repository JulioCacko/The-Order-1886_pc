"""Submission diagnostics must measure CPU work on both supported host platforms."""
from pathlib import Path
import unittest

import test_order1886_read_backing as native

ROOT = Path(__file__).resolve().parents[1]


class GpuCpuStatsTests(unittest.TestCase):
    def test_submission_cpu_time_advances_during_real_work(self):
        source = (ROOT / 'gpu/shadps4/video_core/amdgpu/liverpool.cpp').read_text(encoding='utf-8')
        sample = source[source.index('    if (seq != NoSeq && Ps4Stats::enabled) {'):
                        source.index('\n    FIBER_EXIT;', source.index('    if (seq != NoSeq && Ps4Stats::enabled) {'))]
        header = (ROOT / 'gpu/shim/ps4_toggles.h').as_posix()
        native.ReadBackingTests().compile_and_run(r'''
#include <cassert>
#include <chrono>
#ifdef _WIN32
#include <windows.h>
#else
#include <sys/resource.h>
#endif
''' + '#include "' + header + '"\n' + r'''
using u64=std::uint64_t;
static void Sample() {
    constexpr int seq=1, NoSeq=0;
''' + sample.replace('Ps4Stats::enabled', 'true') + r'''
}
int main() {
    Sample();
    const auto before=Ps4Stats::gpu_user_us.load()+Ps4Stats::gpu_sys_us.load();
    const auto end=std::chrono::steady_clock::now()+std::chrono::milliseconds(100);
    while (std::chrono::steady_clock::now()<end) {
        std::atomic_signal_fence(std::memory_order_seq_cst);
    }
    Sample();
    const auto after=Ps4Stats::gpu_user_us.load()+Ps4Stats::gpu_sys_us.load();
    assert(after>before);
    assert(Ps4Stats::submissions.load()==2);
}
''', cxx=True)


if __name__ == '__main__':
    unittest.main()
