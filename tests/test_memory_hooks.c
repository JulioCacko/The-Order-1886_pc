#undef NDEBUG
#include <stdlib.h>
static void *test_realloc(void *pointer,size_t size);
#define realloc test_realloc
#include "../src/runtime_memory.c"
#undef realloc
#include <assert.h>
static int fail_allocation;
static void *test_realloc(void *pointer,size_t size) {
    return fail_allocation ? NULL : realloc(pointer,size);
}
int32_t *runtime_errno(void) { abort(); }
uintptr_t runtime_lookup(const RuntimeExport *table,size_t count,const char *name) {
    (void)table; (void)count; (void)name; abort();
}
#define COUNT 257
#define PRODUCERS 4
#define PER_PRODUCER 200
static uintptr_t base;
static PendingHook observed[PRODUCERS*PER_PRODUCER+COUNT];
static size_t observed_count;
static pthread_mutex_t observed_lock=PTHREAD_MUTEX_INITIALIZER;
static int reenter;
static void record(int kind,uintptr_t address,uint64_t size) {
    assert(!exclusive_depth && runtime_memory_is_mapped(address,size));
    pthread_mutex_lock(&observed_lock);
    assert(observed_count<sizeof(observed)/sizeof(*observed));
    observed[observed_count++]=(PendingHook){kind,address,size};
    pthread_mutex_unlock(&observed_lock);
    if (reenter && address==base+10) {
        reenter=0;
        write_lock(); queue_hook(HOOK_MAP,base+13,1); write_unlock();
        flush_hooks();
    }
}
static void mapped(uintptr_t address,uint64_t size) { record(HOOK_MAP,address,size); }
static void unmapped(uintptr_t address,uint64_t size) { record(HOOK_UNMAP,address,size); }
static void invalidated(uintptr_t address,uint64_t size) { record(HOOK_INVALIDATE,address,size); }
static void fixture(void) {
    base=(uintptr_t)runtime_low_map(COUNT*PAGE,PROT_READ|PROT_WRITE);
    assert(base);
    write_lock();
    assert(vma_insert(0,(Vma){base,base+COUNT*PAGE,KIND_DIRECT,3,0,0})==0);
#ifdef _WIN32
    region_insert(0,(HostRegion){base,base+COUNT*PAGE,0,1});
#endif
    write_unlock();
    runtime_memory_set_gpu_hooks(NULL,NULL,invalidated);
}
static void mapped_base_guards(void) {
    assert(runtime_memory_clamp(0x1000,1)==0);
    assert(runtime_memory_clamp(base,1)==1);
    assert(runtime_memory_clamp(base+COUNT*PAGE,1)==0);
    write_lock();
    const Vma original=vmas[0];
    vmas[0].end=base+PAGE;
    assert(vma_insert(1,(Vma){base+2*PAGE,base+3*PAGE,KIND_RESERVED,0,0,0})==0);
    assert(vma_insert(2,(Vma){base+3*PAGE,original.end,KIND_DIRECT,3,0,0})==0);
    write_unlock();
    /* A one-byte image-base check accepts mapped sparse prefixes, without claiming
     * that the complete image range is resident or accepting gaps/reservations. */
    assert(runtime_memory_clamp(base,1)==1);
    assert(runtime_memory_clamp(base+PAGE-1,2)==1);
    assert(runtime_memory_clamp(base+PAGE,1)==0);
    assert(runtime_memory_clamp(base+2*PAGE,1)==0);
    assert(runtime_memory_clamp(base+3*PAGE,1)==1);
    write_lock();
    assert(vma_insert(1,(Vma){base+PAGE,base+2*PAGE,KIND_DIRECT,3,0,0})==0);
    write_unlock();
    /* A previously rejected descriptor must be eligible on the next mapping epoch. */
    assert(runtime_memory_clamp(base+PAGE,1)==1);
    write_lock();
    vmas[0]=original; vma_count=1;
    write_unlock();
    assert(runtime_memory_clamp(base+2*PAGE,1)==1);
}
static void batch_notifications(void) {
    BatchEntry entries[COUNT+1];
    for (size_t i=0;i<COUNT;++i)
        entries[i]=(BatchEntry){.start=(void *)(base+i*PAGE),.length=PAGE,.prot=i%2 ? 1 : 3,.operation=2};
    int processed=-1;
    assert(batch_map2(entries,COUNT,&processed,0)==0 && processed==COUNT);
    assert(observed_count==COUNT && pending_capacity>=COUNT && !pending_count);
    for (size_t i=0;i<COUNT;++i)
        assert(observed[i].kind==HOOK_INVALIDATE && observed[i].address==base+i*PAGE && observed[i].size==PAGE);
    observed_count=0;
    entries[COUNT]=(BatchEntry){.operation=99};
    assert(batch_map2(entries,COUNT+1,&processed,0)==INVALID && processed==COUNT);
    assert(observed_count==COUNT && !pending_count);
    for (size_t i=0;i<COUNT;++i) assert(observed[i].address==base+i*PAGE);
    observed_count=0;
    runtime_memory_set_gpu_hooks(mapped,unmapped,invalidated);
    assert(observed_count==COUNT && !pending_count);
    for (size_t i=0;i<COUNT;++i)
        assert(observed[i].kind==HOOK_MAP && observed[i].address==base+i*PAGE && observed[i].size==PAGE);
    observed_count=0;
}
static void reentrant_notifications(void) {
    reenter=1;
    write_lock();
    queue_hook(HOOK_MAP,base+10,1); queue_hook(HOOK_UNMAP,base+11,1); queue_hook(HOOK_INVALIDATE,base+12,1);
    write_unlock(); flush_hooks();
    assert(observed_count==4 && !pending_count && !reenter);
    for (size_t i=0;i<4;++i)
        assert(observed[i].address==base+10+i && observed[i].kind==(int)(i%3));
    observed_count=0;
}
static pthread_barrier_t ready,start;
static void barrier(pthread_barrier_t *value) {
    int result=pthread_barrier_wait(value);
    assert(result==0 || result==PTHREAD_BARRIER_SERIAL_THREAD);
}
static void *producer(void *argument) {
    uintptr_t first=(uintptr_t)argument*PER_PRODUCER;
    write_lock();
    for (size_t i=0;i<PER_PRODUCER;++i) queue_hook((int)((first+i)%3),base+first+i,1);
    write_unlock();
    barrier(&ready); barrier(&start); flush_hooks();
    return NULL;
}
static void concurrent_notifications(void) {
    pthread_t workers[PRODUCERS];
    assert(pthread_barrier_init(&ready,NULL,PRODUCERS+1)==0 && pthread_barrier_init(&start,NULL,PRODUCERS+1)==0);
    for (uintptr_t i=0;i<PRODUCERS;++i) assert(pthread_create(&workers[i],NULL,producer,(void *)i)==0);
    barrier(&ready);
    assert(pending_count==PRODUCERS*PER_PRODUCER && !observed_count);
    barrier(&start); flush_hooks();
    for (size_t i=0;i<PRODUCERS;++i) assert(pthread_join(workers[i],NULL)==0);
    assert(observed_count==PRODUCERS*PER_PRODUCER && !pending_count);
    unsigned char seen[PRODUCERS*PER_PRODUCER]={0};
    for (size_t i=0;i<observed_count;++i) {
        uintptr_t index=observed[i].address-base;
        assert(index<sizeof(seen) && !seen[index] && observed[i].kind==(int)(index%3) && observed[i].size==1);
        seen[index]=1;
    }
    assert(pthread_barrier_destroy(&ready)==0 && pthread_barrier_destroy(&start)==0);
    observed_count=0;
}
static void allocation_failure(void) {
    write_lock();
    queue_hook(HOOK_MAP,base,1);
    PendingHook *previous=pending;
    size_t capacity=pending_capacity;
    fail_allocation=1;
    assert(!reserve_hooks(capacity+1) && pending==previous && pending_capacity==capacity && pending_count==1);
    assert(pending[0].address==base && pending[0].kind==HOOK_MAP);
    fail_allocation=0;
    assert(!reserve_hooks(SIZE_MAX) && pending==previous && pending_count==1);
    write_unlock(); flush_hooks();
    assert(observed_count==1 && !pending_count);
}
int main(int argc,char **argv) {
    if (argc>1 && !strcmp(argv[1],"--allocation-failure")) {
        hook_map=mapped; fail_allocation=1;
        write_lock(); queue_hook(HOOK_MAP,0,1);
        return 99;
    }
    fixture(); mapped_base_guards(); batch_notifications(); reentrant_notifications(); concurrent_notifications(); allocation_failure();
    puts("PASS: memory hook batches, replay, FIFO, reentrancy, concurrency and allocation guards");
    return 0;
}
