#undef NDEBUG
#ifndef _WIN32
#define _GNU_SOURCE
#include <sys/mman.h>
#include <errno.h>
static int fail_map;
static void *test_mmap(void *address,size_t size,int prot,int flags,int fd,off_t offset) {
    if (fail_map && (flags & MAP_FIXED)) { fail_map=0; errno=ENOMEM; return MAP_FAILED; }
    return mmap(address,size,prot,flags,fd,offset);
}
#define mmap test_mmap
#endif
#include "../src/runtime_memory.c"
#ifndef _WIN32
#undef mmap
#endif
#include <assert.h>

int32_t *runtime_errno(void) { abort(); }
uintptr_t runtime_lookup(const RuntimeExport *table,size_t count,const char *name) {
    (void)table; (void)count; (void)name; abort();
}
static unsigned map_calls, unmap_calls;
static uintptr_t dirty_address;
static unsigned char gpu_value=0x77;
static int dirty;
static void mapped(uintptr_t address,uint64_t size) {
    assert(!exclusive_depth && runtime_memory_is_mapped(address,size));
    assert(pthread_mutex_trylock(&mapping_lock)==EBUSY);
    ++map_calls;
}
/* A separate publication thread needs the VM read lock, just like GPU downloads. */
static void *publish(void *unused) {
    (void)unused;
    assert(runtime_memory_write_backing(dirty_address,&gpu_value,1));
    return NULL;
}
static void unmapped(uintptr_t address,uint64_t size) {
    assert(!exclusive_depth && runtime_memory_is_mapped(address,size));
    assert(pthread_mutex_trylock(&mapping_lock)==EBUSY);
    ++unmap_calls;
    if (dirty && address<=dirty_address && dirty_address-address<size) {
        pthread_t writer;
        assert(!pthread_create(&writer,NULL,publish,NULL));
        assert(!pthread_join(writer,NULL));
        dirty=0;
    }
}
static void fixture(uint64_t span) {
#ifdef _WIN32
    section=CreateFileMapping2(INVALID_HANDLE_VALUE,NULL,FILE_MAP_ALL_ACCESS,PAGE_READWRITE,SEC_COMMIT,4*span,NULL,NULL,0);
    assert(section);
    backing_base=MapViewOfFile3(section,GetCurrentProcess(),NULL,0,4*span,0,PAGE_READWRITE,NULL,0);
    assert(backing_base);
    assert(VirtualAlloc2(NULL,(void *)USER_MIN,3*span,MEM_RESERVE|MEM_RESERVE_PLACEHOLDER,PAGE_NOACCESS,NULL,0));
    region_insert(0,(HostRegion){USER_MIN,USER_MIN+3*span,0,0});
#else
    pool_fd=memfd_create("ownership",MFD_CLOEXEC);
    assert(pool_fd>=0 && !ftruncate(pool_fd,4*span));
    backing_base=mmap(NULL,4*span,PROT_READ|PROT_WRITE,MAP_SHARED,pool_fd,0);
    assert(backing_base!=MAP_FAILED);
#endif
    blocks[0]=(Block){0,2*span,0,1};
    live_bytes=2*span;
    memset(backing_base,0x11,span);
    memset(backing_base+span,0x22,span);
    runtime_memory_set_gpu_hooks(mapped,unmapped,NULL);
}
static void *competing_maps(void *unused) {
    (void)unused;
    for (unsigned i=0;i<100;++i) {
        void *address=(void *)USER_MIN;
        assert(!direct_map(&address,65536,3,MAP_FIXED_FLAG,(i%2)*65536,65536));
    }
    return NULL;
}
int main(void) {
    const uint64_t span=65536;
    fixture(span);
    void *first=(void *)USER_MIN,*old_alias=(void *)(USER_MIN+span),*new_alias=(void *)(USER_MIN+2*span);
    assert(!direct_map(&first,span,3,MAP_FIXED_FLAG,0,span));
    assert(!direct_map(&old_alias,span,3,MAP_FIXED_FLAG,0,span));
    assert(!direct_map(&new_alias,span,3,MAP_FIXED_FLAG,span,span));
    dirty_address=(uintptr_t)first; dirty=1;
    assert(direct_map(&first,span,3,MAP_FIXED_FLAG|MAP_NO_OVERWRITE,span,span)==NO_MEMORY);
    assert(dirty && !unmap_calls);
    assert(!direct_map(&first,span,3,MAP_FIXED_FLAG,span,span));
    assert(map_calls==4 && unmap_calls==1 && !dirty);
    assert(*(unsigned char *)first==0x22 && *(unsigned char *)old_alias==0x77);
#ifndef _WIN32
    fail_map=1;
    assert(direct_map(&first,span,3,MAP_FIXED_FLAG,0,span)==NO_MEMORY);
    assert(!fail_map && map_calls==5 && unmap_calls==2 && !pending_count);
    assert(*(unsigned char *)first==0x22 && *(unsigned char *)old_alias==0x77);
#endif
    assert(!direct_unmap(first,span));
    assert(*(unsigned char *)new_alias==0x22);

    /* A later operation in the same batch must see MAP before retiring it. */
    dirty_address=(uintptr_t)first; dirty=1;
    BatchEntry entries[]={
        {.start=first,.offset=0,.length=span,.prot=3,.operation=0},
        {.start=first,.offset=span,.length=span,.prot=3,.operation=0},
        {.start=first,.length=span,.operation=1},
    };
    unsigned before=unmap_calls;
    int processed=-1;
    assert(!batch_map(entries,3,&processed) && processed==3);
    assert(!dirty && unmap_calls==before+2 && !pending_count);
    assert(*(unsigned char *)new_alias==0x22 && *(unsigned char *)old_alias==0x77);

    pthread_t writers[2];
    for (unsigned i=0;i<2;++i) assert(!pthread_create(&writers[i],NULL,competing_maps,NULL));
    for (unsigned i=0;i<2;++i) assert(!pthread_join(writers[i],NULL));
    assert(!direct_unmap(first,span));

    /* Physical release must notify while every retiring VMA still has backing. */
    dirty_address=(uintptr_t)old_alias; dirty=1;
    assert(!direct_release(0,span));
    assert(!dirty && !runtime_memory_is_mapped((uintptr_t)old_alias,span));
    assert(backing_base[0]==0 && *(unsigned char *)new_alias==0x22);
    assert(!direct_unmap(new_alias,span));
    puts("PASS: GPU ownership retires before MAP_FIXED, batch unmap and physical release; live aliases preserved");
    return 0;
}
