#undef NDEBUG
#include "../src/runtime_memory.c"
#include <assert.h>
#ifndef _WIN32
#include <signal.h>
#endif

int32_t *runtime_errno(void) { abort(); }
uintptr_t runtime_lookup(const RuntimeExport *table,size_t count,const char *name) {
    (void)table; (void)count; (void)name; abort();
}
static void *output;
static unsigned faults;
static void protect_output(int inaccessible) {
#ifdef _WIN32
    DWORD old;
    assert(VirtualProtect(output,PAGE,inaccessible==2 ? PAGE_NOACCESS :
                          inaccessible ? PAGE_READONLY : PAGE_READWRITE,&old));
#else
    assert(!mprotect(output,PAGE,inaccessible==2 ? PROT_NONE :
                     inaccessible ? PROT_READ : PROT_READ|PROT_WRITE));
#endif
}
static void output_fault(void) {
    // A protected guest result may call back into GPU work needing these locks.
    assert(!exclusive_depth);
#ifdef _WIN32
    assert(!read_depth);
    assert(TryAcquireSRWLockExclusive(&lock));
    ReleaseSRWLockExclusive(&lock);
#else
    assert(!pthread_rwlock_trywrlock(&lock));
    assert(!pthread_rwlock_unlock(&lock));
#endif
    assert(!pthread_mutex_trylock(&mapping_lock));
    assert(!pthread_mutex_unlock(&mapping_lock));
    ++faults;
    protect_output(0);
}
#ifdef _WIN32
static LONG CALLBACK fault_handler(EXCEPTION_POINTERS *exception) {
    if(exception->ExceptionRecord->ExceptionCode!=EXCEPTION_ACCESS_VIOLATION)
        return EXCEPTION_CONTINUE_SEARCH;
    uintptr_t at=exception->ExceptionRecord->ExceptionInformation[1];
    if(at<(uintptr_t)output || at-(uintptr_t)output>=PAGE) return EXCEPTION_CONTINUE_SEARCH;
    output_fault(); return EXCEPTION_CONTINUE_EXECUTION;
}
#else
static void fault_handler(int signal,siginfo_t *info,void *context) {
    (void)signal; (void)context;
    uintptr_t at=(uintptr_t)info->si_addr;
    assert(at>=(uintptr_t)output && at-(uintptr_t)output<PAGE);
    output_fault();
}
#endif

int main(void) {
    output=runtime_low_map(PAGE,PROT_READ|PROT_WRITE);
    assert(output);
#ifdef _WIN32
    void *handler=AddVectoredExceptionHandler(1,fault_handler); assert(handler);
#else
    struct sigaction action={.sa_sigaction=fault_handler,.sa_flags=SA_SIGINFO};
    assert(!sigemptyset(&action.sa_mask) && !sigaction(SIGSEGV,&action,NULL));
#endif
    int64_t physical;
    assert(!direct_allocate(0,POOL_SIZE,4*PAGE,PAGE,0,&physical));
    *(int64_t *)output=-1; protect_output(1);
    assert(!direct_allocate(0,POOL_SIZE,PAGE,PAGE,0,output));
    assert(*(int64_t *)output>=0);
    *(void **)output=NULL; protect_output(1);
    assert(!direct_map(output,PAGE,3,0,physical,PAGE));
    void *mapped=*(void **)output;
    *(void **)output=NULL; protect_output(1);
    assert(!map_flexible(output,PAGE,3,0));
    *(void **)output=NULL; protect_output(1);
    assert(!reserve_range(output,PAGE,0,PAGE));
    memset(output,0,PAGE); protect_output(1);
    assert(!query_protection(mapped,output,(void **)((char *)output+16),(uint32_t *)((char *)output+32)));
    assert(*(void **)output==mapped);
    memset(output,0,PAGE); protect_output(1);
    assert(!virtual_query(mapped,0,output,sizeof(VirtualQueryInfo)));
    assert(((VirtualQueryInfo *)output)->start==(uintptr_t)mapped);
    memset(output,0,PAGE); protect_output(1);
    assert(!direct_memory_type(physical,output,(void **)((char *)output+16),(void **)((char *)output+32)));
    BatchEntry *entry=output;
    *entry=(BatchEntry){.length=PAGE,.offset=physical,.prot=3,.operation=0};
    protect_output(1);
    int processed=-1;
    assert(!batch_map2(entry,1,&processed,0) && processed==1 && entry->start);
    // Input reads can fault too: take the in/out snapshot before acquiring locks.
    *(void **)output=NULL; protect_output(2);
    assert(!direct_map(output,PAGE,3,0,physical,PAGE));
    *(void **)output=NULL; protect_output(2);
    assert(!map_flexible(output,PAGE,3,0));
    *(void **)output=NULL; protect_output(2);
    assert(!reserve_range(output,PAGE,0,PAGE));
    *entry=(BatchEntry){.length=PAGE,.offset=physical,.prot=3,.operation=0};
    protect_output(2);
    assert(!batch_map2(entry,1,&processed,0) && processed==1 && entry->start);
    assert(faults==12);
    BatchEntry partial[]={
        {.length=PAGE,.offset=physical,.prot=3,.operation=0},
        {.start=(void *)0xbeef,.operation=99},
    };
    protect_output(1);
    assert(batch_map2(partial,2,output,0)==INVALID);
    assert(*(int *)output==1 && partial[0].start && partial[1].start==(void *)0xbeef);
    assert(partial[0].length==PAGE && partial[0].offset==(uint64_t)physical && faults==13);
    *(void **)output=(void *)0xbeef; protect_output(2);
    assert(direct_map(output,0,3,0,physical,PAGE)==INVALID);
    assert(faults==13);
    protect_output(0);
    assert(*(void **)output==(void *)0xbeef);
#ifdef _WIN32
    assert(RemoveVectoredExceptionHandler(handler));
#endif
    puts("PASS: protected VM API inputs and outputs fault outside memory locks");
}
