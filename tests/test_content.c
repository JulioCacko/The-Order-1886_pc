#undef NDEBUG
#include "runtime.h"
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
typedef int32_t (ABI *Module)(uint16_t);
typedef int32_t (ABI *Init)(const void *,void *);
typedef int32_t (ABI *Param)(uint32_t,int32_t *);
typedef int32_t (ABI *List)(uint32_t,void *,uint32_t,uint32_t *);
typedef int32_t (ABI *Addon)(uint32_t,const void *,void *);
#define GET(t,n) ((t)runtime_content_resolve(n))
static void unexpected_cleanup(void) { fputs("unexpected fatal cleanup\n",stderr); abort(); }
int main(int argc,char **argv) {
    Module load=GET(Module,"g8cM39EUZ6o#libSceSysmodule");
    Module loaded=GET(Module,"fMP5NHUOaMk#libSceSysmodule");
    Module unload=GET(Module,"eR2bZFAAU0Q#libSceSysmodule");
    Init init=GET(Init,"R9lA82OraNs#libSceAppContent");
    Param param=GET(Param,"99b82IKXpH4#libSceAppContent");
    List list=GET(List,"xnd8BJzAxmk#libSceAppContent");
    Addon mount=GET(Addon,"VANhIWcqYak#libSceAppContent"), key=GET(Addon,"XTWR0UXvcgs#libSceAppContent");
    assert(load && loaded && unload && init && param && list && mount && key);
    assert(!runtime_content_resolve("g8cM39EUZ6o#libkernel"));
    if (argc>2 && !strcmp(argv[1],"--sfo")) {
        if (!runtime_content_configure_sfo(argv[2])) { fputs("Rejected SFO metadata\n",stderr); return 2; }
        unsigned char text[9]; memset(text,0xa5,sizeof(text));
        assert(runtime_sfo_value(argv[2],"TITLE_ID",(char *)text,5,NULL) && memchr(text,0,5));
        for (unsigned i=5;i<sizeof(text);++i) assert(text[i]==0xa5);
        for (unsigned i=0;i<5;++i) { int32_t value; assert(param(i,&value)==0); }
        puts("PASS: AppContent SFO metadata"); return 0;
    }
    if (argc>1 && !strcmp(argv[1],"--missing")) {
        unsigned char initial[32]={0},boot[40]; int32_t value=99;
        assert(load(0xb4)==0 && (uint32_t)init(initial,boot)==0x80d90002);
        assert((uint32_t)param(0,&value)==0x80d90002 && value==99);
        assert(unload(0xb4)==0);
        puts("PASS: absent metadata returns parameter error without a process stop"); return 0;
    }
    const uint32_t profile[]={3,13,0x80000000,0,7};
    runtime_content_configure(profile);
    if (argc>1 && !strcmp(argv[1],"--late")) {
        assert(atexit(unexpected_cleanup)==0 && load(0xb4)==0);
        runtime_content_configure(profile); return 99;
    }
    int32_t early=0; assert(param(1,&early)==0 && early==13);
    if (argc>1 && !strcmp(argv[1],"--unknown")) {
        /* Other system modules are host-provided: reference counted, independent. */
        assert((uint32_t)loaded(0xb5)==0x805a1001);
        assert(load(0xb5)==0 && loaded(0xb5)==0 && (uint32_t)loaded(0xb4)==0x805a1001);
        assert(unload(0xb5)==0 && (uint32_t)loaded(0xb5)==0x805a1001);
        puts("PASS: independent module references"); return 0;
    }
    assert((uint32_t)loaded(0)==0x805a1000);
    assert((uint32_t)loaded(0xb4)==0x805a1001);
    assert((uint32_t)unload(0xb4)==0x805a1001);
    assert(load(0xb4)==0 && load(0xb4)==0 && loaded(0xb4)==0);
    unsigned char initial[32]={0};
    struct { unsigned char boot[40]; uint32_t canary; } b;
    memset(&b,0xa5,sizeof(b));
    assert((uint32_t)init(NULL,b.boot)==0x80d90002);
    initial[31]=1; assert((uint32_t)init(initial,b.boot)==0x80d90002); initial[31]=0;
    assert(b.boot[0]==0xa5 && init(initial,b.boot)==0);
    for (unsigned i=0;i<40;++i) assert(b.boot[i]==0);
    assert(b.canary==0xa5a5a5a5);
    b.boot[0]=0xcc; assert((uint32_t)init(initial,b.boot)==0x80d90003 && b.boot[0]==0xcc);
    struct { int32_t value; uint32_t canary; } result={-1,0x1234};
    for (unsigned i=0;i<5;++i) {
        assert(param(i,&result.value)==0 && (uint32_t)result.value==profile[i]);
        assert(result.canary==0x1234);
    }
    result.value=77;
    assert((uint32_t)param(5,&result.value)==0x80d90002 && result.value==77);
    assert((uint32_t)param(0,NULL)==0x80d90002);
    unsigned char entries[48]; memset(entries,0xaa,sizeof(entries));
    struct { uint32_t hits,canary; } h={99,0xabcdef};
    assert(list(0,NULL,0,&h.hits)==0 && h.hits==0 && h.canary==0xabcdef);
    assert(list(0,entries,2,&h.hits)==0 && h.hits==0);
    for (unsigned i=0;i<sizeof(entries);++i) assert(entries[i]==0xaa);
    assert((uint32_t)list(0,NULL,0,NULL)==0x80d90002);
    assert(list(7,NULL,0,&h.hits)==0 && h.hits==0);
    unsigned char label[20]={0},addon_output[16]; memset(addon_output,0xcc,sizeof(addon_output));
    assert((uint32_t)mount(0,NULL,addon_output)==0x80d90002);
    assert((uint32_t)mount(0,label,NULL)==0x80d90002);
    assert((uint32_t)mount(0,label,addon_output)==0x80d90005);
    assert((uint32_t)key(0,NULL,addon_output)==0x80d90002);
    assert((uint32_t)key(0,label,NULL)==0x80d90002);
    assert((uint32_t)key(0,label,addon_output)==0x80d90007);
    for (unsigned i=0;i<sizeof(addon_output);++i) assert(addon_output[i]==0xcc);
    assert(unload(0xb4)==0 && loaded(0xb4)==0);
    assert((uint32_t)init(initial,b.boot)==0x80d90003);
    assert(unload(0xb4)==0 && (uint32_t)loaded(0xb4)==0x805a1001);
    assert(load(0xb4)==0 && init(initial,b.boot)==0 && unload(0xb4)==0);
    puts("PASS: AppContent lifecycle, profile and output boundaries");
    return 0;
}
