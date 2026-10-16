#define _GNU_SOURCE
#undef NDEBUG
#include "../src/runtime_save_trace.h"
#include <assert.h>

int main(void) {
    const int enabled=runtime_save_trace_enabled();
    RuntimeSaveTraceApi api=RUNTIME_SAVE_TRACE_INIT;
    RuntimeSaveTraceCall call=runtime_save_trace_begin(&api,"fixture.error",0,"user=%d bytes=%d",1,64);
    assert(runtime_save_trace_end(call,(int32_t)0x809f0008,7)==(int32_t)0x809f0008);
    assert(api.lines==(enabled ? 2u : 0u));
    RuntimeSaveTraceApi poll=RUNTIME_SAVE_TRACE_INIT;
    for (int i=0;i<10000;++i) {
        call=runtime_save_trace_begin(&poll,"fixture.status",1,"%s","");
        assert(runtime_save_trace_end(call,2,2)==2);
    }
    if (enabled) {
        assert(poll.calls==10000 && poll.lines>=2 && poll.lines<RUNTIME_SAVE_TRACE_LINES);
        const uint64_t lines=poll.lines;
        call=runtime_save_trace_begin(&poll,"fixture.status",1,"%s","");
        assert(runtime_save_trace_end(call,3,3)==3);
        assert(poll.lines>lines && poll.last_result==3 && poll.last_status==3);
    } else assert(!poll.calls && !poll.lines);
    for (int i=0;i<1000;++i) {
        call=runtime_save_trace_begin(&poll,"fixture.status",1,"%s","");
        assert(runtime_save_trace_end(call,i&1,i&1)==(i&1));
    }
    if (enabled) assert(poll.lines==RUNTIME_SAVE_TRACE_LINES);
    const uint64_t before=runtime_save_trace_ns();
    const uint64_t after=runtime_save_trace_ns();
    assert(before<=after);
    assert(runtime_save_trace_thread()!=0);
    puts("save trace test: ok");
    return 0;
}
