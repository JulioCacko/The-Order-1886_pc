"""Repeated accepted game flip mode must not write a warning every frame."""
from pathlib import Path
import unittest

import test_order1886_read_backing as native
from test_order1886_srt_codegen import function_body

ROOT = Path(__file__).resolve().parents[1]


class FlipLoggingTests(unittest.TestCase):
    def test_real_flip_entry_point_limits_mode_three_but_keeps_validation(self):
        source = (ROOT / 'gpu/shadps4/core/libraries/videoout/video_out.cpp').read_text(encoding='utf-8')
        flip = function_body(source, 's32 PS4_SYSV_ABI sceVideoOutSubmitFlip(')
        native.ReadBackingTests().compile_and_run(r'''
#include <atomic>
#include <cassert>
#include <cstdint>
#include <thread>
#include <vector>
using s32=int32_t; using s64=int64_t;
#define PS4_SYSV_ABI
constexpr s32 ORBIS_OK=0, ORBIS_VIDEO_OUT_ERROR_INVALID_HANDLE=-1,
    ORBIS_VIDEO_OUT_ERROR_INVALID_INDEX=-2, ORBIS_VIDEO_OUT_ERROR_FLIP_QUEUE_FULL=-3;
static std::atomic<unsigned> warnings{}, errors{}, debug{}, submissions{};
#define LOG_WARNING(...) (++warnings)
#define LOG_ERROR(...) (++errors)
#define LOG_DEBUG(...) (++debug)
struct Slot { int group_index=0; };
struct Port { Slot buffer_slots[16]; };
struct Driver {
    Port port;
    bool full=false;
    Port* GetPort(int handle) { return handle==1 ? &port : nullptr; }
    bool SubmitFlip(Port* target, int index, s64 arg) {
        assert(target==&port && index>=-1 && index<=15 && arg==123);
        ++submissions;
        return !full;
    }
} instance;
static Driver* driver=&instance;
''' + flip + r'''
int main() {
    assert(sceVideoOutSubmitFlip(0,0,3,123)==ORBIS_VIDEO_OUT_ERROR_INVALID_HANDLE);
    assert(warnings==0 && errors==1 && submissions==0);
    std::vector<std::thread> threads;
    for (int i=0;i<8;++i) threads.emplace_back([] {
        for(int j=0;j<1250;++j) assert(sceVideoOutSubmitFlip(1,0,3,123)==ORBIS_OK);
    });
    for(auto& thread:threads) thread.join();
    assert(submissions==10000 && warnings==1 && debug==10000);
    assert(sceVideoOutSubmitFlip(1,-1,1,123)==ORBIS_OK);
    assert(warnings==1);
    assert(sceVideoOutSubmitFlip(1,0,77,123)==ORBIS_OK);
    assert(sceVideoOutSubmitFlip(1,0,77,123)==ORBIS_OK);
    assert(warnings==3);
    assert(sceVideoOutSubmitFlip(1,16,3,123)==ORBIS_VIDEO_OUT_ERROR_INVALID_INDEX);
    instance.port.buffer_slots[0].group_index=-1;
    assert(sceVideoOutSubmitFlip(1,0,3,123)==ORBIS_VIDEO_OUT_ERROR_INVALID_INDEX);
    instance.full=true;
    assert(sceVideoOutSubmitFlip(1,1,3,123)==ORBIS_VIDEO_OUT_ERROR_FLIP_QUEUE_FULL);
    assert(errors==4 && warnings==3 && submissions==10004);
}
''', cxx=True)


if __name__ == '__main__':
    unittest.main()
