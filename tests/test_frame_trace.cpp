#include <cassert>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
#include "ps4_frame_trace.h"

int main(int argc, char** argv) {
    assert(argc == 2);
    {
        Ps4PerfStats::FrameTrace disabled(nullptr);
        assert(!disabled.Enabled());
        disabled.Record("guest_flip", 10, 1, 4096, false);
    }
    {
        Ps4PerfStats::FrameTrace writer(argv[1]);
        assert(writer.Enabled());
        writer.Record("host_present", 10, 0, 0, true);
        writer.Record("guest_flip", 20, 99, 4096, false);
        Ps4PerfStats::FrameTrace existing(argv[1]);
        assert(!existing.Enabled()); // an existing evidence file must never be truncated
    }
    std::ifstream input(argv[1]);
    std::ostringstream content;
    content << input.rdbuf();
    assert(content.str() == "event,timestamp_ns,render_serial,buffer_address,loading\n"
                            "host_present,10,0,0,1\nguest_flip,20,99,4096,0\n");
    return 0;
}
