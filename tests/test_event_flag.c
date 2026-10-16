#undef NDEBUG
#include "../src/runtime_event_flag.c"
#include <assert.h>
static _Thread_local int test_priority=700;
int runtime_thread_priority(void) { return test_priority; }
typedef int32_t (ABI *Create)(uintptr_t *,const char *,uint32_t,uint64_t,const void *);
typedef int32_t (ABI *Pattern)(uintptr_t,uint64_t);
typedef int32_t (ABI *Wait)(uintptr_t,uint64_t,uint32_t,uint64_t *,uint32_t *);
typedef int32_t (ABI *Poll)(uintptr_t,uint64_t,uint32_t,uint64_t *);
typedef int32_t (ABI *Delete)(uintptr_t);
typedef int32_t (ABI *Cancel)(uintptr_t,uint64_t,int32_t *);
#define GET(type,nid) ((type)runtime_event_flag_resolve(nid))
static Create create;
static Pattern set,clear;
static Wait wait_flag;
static Poll poll_flag;
static Delete delete_flag;
static Cancel cancel_flag;
static void setup(void) {
    create=GET(Create,"BpFoboUJoZU#libkernel"); delete_flag=GET(Delete,"8mql9OcQnd4#libkernel");
    set=GET(Pattern,"IOnSvHzqu6A#libkernel"); clear=GET(Pattern,"7uhBFWRAS60#libkernel");
    wait_flag=GET(Wait,"JTvBflhYazQ#libkernel"); poll_flag=GET(Poll,"9lvj5DjHZiA#libkernel");
    cancel_flag=GET(Cancel,"PZku4ZrXJqg#libkernel");
    assert(create && delete_flag && set && clear && wait_flag && poll_flag && cancel_flag);
    assert(!runtime_event_flag_resolve("BpFoboUJoZU#libc"));
}
static void lifecycle(void) {
    struct { uintptr_t id; uint64_t canary; } handle={0,UINT64_C(0xabcdef0123456789)};
    const uint64_t high=UINT64_C(1)<<63,initial=high|5;
    assert((uint32_t)create(NULL,"test",0,0,NULL)==0x80020016);
    assert((uint32_t)create(&handle.id,NULL,0,0,NULL)==0x80020016);
    assert((uint32_t)create(&handle.id,"test",3,0,NULL)==0x80020016);
    assert((uint32_t)create(&handle.id,"test",0x30,0,NULL)==0x80020016);
    assert((uint32_t)create(&handle.id,"test",0x40,0,NULL)==0x80020016);
    assert((uint32_t)create(&handle.id,"test",0,0,&handle)==0x80020016);
    assert((uint32_t)create(&handle.id,"01234567890123456789012345678901",0,0,NULL)==0x8002003f);
    assert(create(&handle.id,"test",0x20,initial,NULL)==0 && handle.canary==UINT64_C(0xabcdef0123456789));
    uint64_t observed=0;
    assert(poll_flag(handle.id,5,1,&observed)==0 && observed==initial);
    assert(poll_flag(handle.id,6,2,&observed)==0 && observed==initial);
    assert((uint32_t)poll_flag(handle.id,6,1,&observed)==0x80020010 && observed==initial);
    assert(poll_flag(handle.id,5,0x21,&observed)==0 && observed==initial);
    assert(poll_flag(handle.id,high,1,&observed)==0 && observed==high);
    assert(set(handle.id,7)==0 && clear(handle.id,5)==0);
    assert(poll_flag(handle.id,5,0x11,&observed)==0 && observed==5);
    assert((uint32_t)poll_flag(handle.id,1,1,&observed)==0x80020010 && observed==0);
    uint32_t modes[]={0,3,0x31,0x41};
    for (size_t i=0;i<sizeof(modes)/sizeof(*modes);++i)
        assert((uint32_t)poll_flag(handle.id,1,modes[i],NULL)==0x80020016);
    assert((uint32_t)poll_flag(handle.id,0,1,NULL)==0x80020016);
    uint32_t timeout=0;
    assert((uint32_t)wait_flag(handle.id,1,1,&observed,&timeout)==0x8002003c && observed==0 && !timeout);
    timeout=1000;
    assert((uint32_t)wait_flag(handle.id,1,1,&observed,&timeout)==0x8002003c && !timeout);
    assert(set(handle.id,1)==0); timeout=1000000;
    assert(wait_flag(handle.id,1,1,NULL,&timeout)==0 && timeout==1000000);
    uintptr_t old=handle.id;
    assert(delete_flag(old)==0 && (uint32_t)delete_flag(old)==0x80020003);
    assert((uint32_t)set(old,1)==0x80020003 && (uint32_t)clear(old,0)==0x80020003);
    assert(create(&handle.id,"new",0,0,NULL)==0 && handle.id!=old);
    assert((uint32_t)poll_flag(old,1,1,NULL)==0x80020003 && delete_flag(handle.id)==0);
}
typedef struct {
    uintptr_t id;
    uint64_t bits,observed;
    uint32_t mode,timeout;
    int priority,infinite;
    int32_t result;
} Task;
static void *worker(void *context) {
    Task *task=context; test_priority=task->priority;
    task->result=wait_flag(task->id,task->bits,task->mode,&task->observed,task->infinite ? NULL : &task->timeout);
    return NULL;
}
static Task task(uintptr_t id,uint64_t bits,uint32_t mode,int priority) {
    return (Task){.id=id,.bits=bits,.mode=mode,.priority=priority,.timeout=5000000,.result=99};
}
static void enrolled(uintptr_t id,unsigned count) {
    const struct timespec nap={0,1000000};
    for (int i=0;i<2000;++i) {
        if (runtime_event_flag_waiters(id)==count) return;
        nanosleep(&nap,NULL);
    }
    assert(!"event flag waiter enrollment timed out");
}
static void ordering(uint32_t attr) {
    uintptr_t id; assert(create(&id,"ordered",attr,0,NULL)==0);
    Task a=task(id,1,0x21,500),b=task(id,1,0x21,700);
    pthread_t first,second;
    assert(pthread_create(&first,NULL,worker,&a)==0); enrolled(id,1);
    assert(pthread_create(&second,NULL,worker,&b)==0); enrolled(id,2);
    assert(set(id,1)==0);
    if (attr&2) { assert(pthread_join(second,NULL)==0 && b.result==0 && b.observed==1); }
    else { assert(pthread_join(first,NULL)==0 && a.result==0 && a.observed==1); }
    assert(runtime_event_flag_waiters(id)==1 && set(id,1)==0);
    if (attr&2) { assert(pthread_join(first,NULL)==0 && a.result==0); }
    else { assert(pthread_join(second,NULL)==0 && b.result==0); }
    assert(a.timeout<=5000000 && b.timeout<=5000000 && delete_flag(id)==0);
}
static void single_waiter(void) {
    uintptr_t id; assert(create(&id,"single",0x11,0,NULL)==0);
    Task a=task(id,1,1,700); a.infinite=1;
    pthread_t first; assert(pthread_create(&first,NULL,worker,&a)==0); enrolled(id,1);
    uint32_t timeout=0;
    assert((uint32_t)wait_flag(id,1,1,NULL,&timeout)==0x80020001);
    assert((uint32_t)poll_flag(id,1,1,NULL)==0x80020001);
    int32_t count=0;
    assert(cancel_flag(id,8,&count)==0 && count==1);
    assert(pthread_join(first,NULL)==0 && (uint32_t)a.result==0x80020055 && a.observed==8);
    assert(poll_flag(id,8,1,NULL)==0 && delete_flag(id)==0);
}
static void cancellation_and_delete(void) {
    uintptr_t id; assert(create(&id,"multi",0x21,0,NULL)==0);
    Task a=task(id,1,1,700),b=task(id,2,1,700); pthread_t first,second;
    assert(pthread_create(&first,NULL,worker,&a)==0); enrolled(id,1);
    assert(pthread_create(&second,NULL,worker,&b)==0); enrolled(id,2);
    int32_t count=-1;
    assert(cancel_flag(id,8,&count)==0 && count==2);
    assert(pthread_join(first,NULL)==0 && pthread_join(second,NULL)==0);
    assert((uint32_t)a.result==0x80020055 && (uint32_t)b.result==0x80020055);
    assert(a.observed==8 && b.observed==8 && !a.timeout && !b.timeout);
    a=task(id,1,1,700); b=task(id,2,1,700);
    assert(pthread_create(&first,NULL,worker,&a)==0); enrolled(id,1);
    assert(pthread_create(&second,NULL,worker,&b)==0); enrolled(id,2);
    assert(delete_flag(id)==0);
    assert(pthread_join(first,NULL)==0 && pthread_join(second,NULL)==0);
    assert((uint32_t)a.result==0x8002000d && (uint32_t)b.result==0x8002000d);
    assert(!a.timeout && !b.timeout && (uint32_t)poll_flag(id,1,1,NULL)==0x80020003);
}
static void conditions(void) {
    uintptr_t id; assert(create(&id,"conditions",0x21,0,NULL)==0);
    Task a=task(id,3,0x21,700),b=task(id,1,2,700); pthread_t first,second;
    assert(pthread_create(&first,NULL,worker,&a)==0); enrolled(id,1);
    assert(pthread_create(&second,NULL,worker,&b)==0); enrolled(id,2);
    assert(set(id,1)==0 && pthread_join(second,NULL)==0 && b.result==0 && b.observed==1);
    assert(runtime_event_flag_waiters(id)==1 && set(id,2)==0);
    assert(pthread_join(first,NULL)==0 && a.result==0 && a.observed==3);
    a=task(id,1,1,700); b=task(id,1,1,700);
    assert(pthread_create(&first,NULL,worker,&a)==0); enrolled(id,1);
    assert(pthread_create(&second,NULL,worker,&b)==0); enrolled(id,2);
    assert(set(id,1)==0 && pthread_join(first,NULL)==0 && pthread_join(second,NULL)==0);
    assert(a.result==0 && b.result==0 && a.observed==1 && b.observed==1);
    assert(delete_flag(id)==0);
}
int main(void) {
    setup(); lifecycle(); ordering(0x21); ordering(0x22); single_waiter(); conditions(); cancellation_and_delete();
    puts("PASS: event flag ABI, masks, FIFO/priority, conditions, timeouts, cancellation and deletion");
    return 0;
}
