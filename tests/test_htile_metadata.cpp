#undef NDEBUG
#include "../gpu/shadps4/video_core/texture_cache/surface_metadata.h"
#include <cassert>
#include <thread>

using VideoCore::SurfaceMetadata;
int main() {
    SurfaceMetadata metadata;
    using Type=SurfaceMetadata::Type;
    constexpr std::uint64_t base=0x10000000, size=4096;
    metadata.Register(base,1,Type::HTile,~0u,1,false);
    assert(!metadata.HtileWord(base,size)); // No observed clear range yet.
    assert(metadata.Clear(base,size));
    assert(metadata.HtileExtent(base)==size);
    assert(!metadata.Clear(base,0) && !metadata.Clear(base,3));
    assert(metadata.HtileExtent(base)==size);
    assert(metadata.HtileWord(base,size)==0xfffc0000u);
    assert(metadata.HtileWord(base+4,4)==0xfffc0000u);
    assert(!metadata.HtileWord(base+size-4,8));
    assert(!metadata.HtileWord(base,3));
    assert(!metadata.HtileWord(base,0));
    assert(metadata.Touch(base,0,false));
    assert(metadata.HtileExtent(base)==size);
    assert(metadata.HtileWord(base,size)==0xfffc000fu);
    metadata.Write(base+64,4);
    assert(!metadata.HtileWord(base,size)); // Interior shader/CPU writes retain real words.
    metadata.Clear(base,size);
    assert(metadata.HtileWord(base,size)==0xfffc0000u);
    metadata.Write(base-4,8);
    assert(!metadata.HtileWord(base,size));

    metadata.Register(base,2,Type::HTile,0,1,true);
    metadata.Erase(base,1); // Old image cannot erase its replacement's state.
    assert(metadata.TypeAt(base)==Type::HTile);
    assert(!metadata.IsCleared(base,0) && !metadata.HtileWord(base,size));
    metadata.Clear(base,size);
    assert(metadata.HtileWord(base,size)==0xfffff3f0u);
    metadata.Touch(base,0,false);
    assert(metadata.HtileWord(base,size)==0xfffff3ffu);
    metadata.Fill(base,size,0xfffff3ffu);
    assert(!metadata.HtileWord(base,size) && !metadata.IsCleared(base,0));
    metadata.Fill(base,size,0);
    assert(metadata.HtileWord(base,size)==0xfffff3f0u);
    metadata.Fill(base+8,4,0);
    assert(!metadata.HtileWord(base,size));
    metadata.Clear(base,size);
    metadata.Touch(base,0,false);
    metadata.Register(base,2,Type::HTile,~0u,1,true); // Rebinding same owner preserves draws.
    assert(!metadata.IsCleared(base,0));
    assert(metadata.HtileWord(base,size)==0xfffff3ffu);
    metadata.Register(base,2,Type::HTile,~0u,32,true); // Geometry change resets derived state.
    assert(!metadata.HtileWord(base,size));
    assert(!metadata.Clear(base,size));
    assert(!metadata.IsCleared(base,31));
    assert(!metadata.IsCleared(base,32));
    assert(!metadata.Touch(base,32,false));
    assert(!metadata.HtileWord(base,size));
    metadata.Register(base,3,Type::HTile,~0u,33,false);
    assert(!metadata.Clear(base,size));
    assert(!metadata.HtileWord(base,size));

    metadata.Register(base,4,Type::CMask,~0u,1,false);
    assert(metadata.Clear(base,size) && metadata.IsCleared(base,0));
    metadata.Fill(base,size,0xccccccccu);
    assert(metadata.IsCleared(base,0));
    assert(!metadata.HtileWord(base,size));
    metadata.Touch(base,0,false);
    assert(!metadata.IsCleared(base,0));
    metadata.Erase(base,4);
    assert(!metadata.TypeAt(base) && !metadata.Clear(base,size));
    assert(!metadata.Touch(base,0,false));

    metadata.Register(base,5,Type::HTile,~0u,1,false);
    auto writes=[&] {
        for(unsigned i=0;i<1000;++i) {
            metadata.Clear(base,size);
            metadata.Touch(base,0,false);
            metadata.Write(base+4,4);
        }
    };
    std::thread writer(writes);
    for(unsigned i=0;i<1000;++i) {
        const auto word=metadata.HtileWord(base,size);
        assert(!word || *word==0xfffc0000u || *word==0xfffc000fu);
    }
    writer.join();
    metadata.Erase(base,5);
    assert(!metadata.HtileWord(base,size));
    metadata.Register(base,6,Type::HTile,~0u,1,false);
    metadata.Clear(base,size);
    metadata.Register(base+64,7,Type::CMask);
    assert(!metadata.HtileWord(base,4));
    metadata.Erase(base+64,7);
    metadata.Clear(base,size);
    assert(metadata.HtileWord(base,size));
    metadata.Register(UINT64_MAX-3,8,Type::HTile,~0u,1,false);
    assert(!metadata.Clear(UINT64_MAX-3,8));
    assert(!metadata.HtileWord(UINT64_MAX-3,4));
    metadata.Unmap(base+4,4);
    assert(!metadata.TypeAt(base));
    metadata.Register(base,6,Type::HTile,~0u,1,false);
    assert(!metadata.HtileWord(base,size));
}
