/* PS4 event flags: bit conditions, ordered waiters and cancellation/deletion wakeups. */
#define _GNU_SOURCE
#include "runtime.h"
#include <pthread.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#define ERR(n) ((int32_t)(UINT32_C(0x80020000)|(n)))
typedef struct FlagWaiter {
    uint64_t bits, observed;
    uint32_t mode;
    int priority, done;
    int32_t result;
    pthread_cond_t event;
    struct FlagWaiter *next;
} FlagWaiter;
typedef struct EventFlag {
    uintptr_t id;
    uint64_t bits;
    uint32_t attr;
    unsigned active;
    int deleted;
    FlagWaiter *first;
    struct EventFlag *next;
} EventFlag;
static pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;
static EventFlag *registry;
static uintptr_t next_id=1;
static size_t created, deleted, waits, signals, timeouts;
static void host_check(int error) {
    if (error) { fprintf(stderr,"STOP: event flag host error %d\n",error); exit(21); }
}
#ifdef _WIN32
#define WAIT_CLOCK CLOCK_REALTIME
#else
#define WAIT_CLOCK CLOCK_MONOTONIC
#endif
static uint64_t now_ns(void) {
    struct timespec t;
    if (clock_gettime(WAIT_CLOCK,&t)) { perror("event flag clock_gettime"); exit(21); }
    return (uint64_t)t.tv_sec*1000000000+(uint64_t)t.tv_nsec;
}
static EventFlag *find(uintptr_t id) {
    for (EventFlag *flag=registry;flag;flag=flag->next) if (flag->id==id) return flag;
    return NULL;
}
static int matches(const EventFlag *flag,uint64_t bits,uint32_t mode) {
    return (mode&3)==1 ? (flag->bits&bits)==bits : (flag->bits&bits)!=0;
}
static void consume(EventFlag *flag,uint64_t bits,uint32_t mode) {
    if (mode&0x10) flag->bits=0;
    else if (mode&0x20) flag->bits&=~bits;
}
static ABI int32_t flag_create(uintptr_t *out,const char *name,uint32_t attr,uint64_t bits,const void *options) {
    if (!out || !name || options || (attr&~UINT32_C(0x33)) || (attr&3)==3 || (attr&0x30)==0x30) return ERR(22);
    if (strnlen(name,32)>=32) return ERR(63);
    EventFlag *flag=calloc(1,sizeof(*flag));
    if (!flag) return ERR(12);
    pthread_mutex_lock(&lock);
    if (next_id==UINTPTR_MAX) { pthread_mutex_unlock(&lock); free(flag); return ERR(28); }
    flag->id=next_id++; flag->bits=bits; flag->attr=attr;
    flag->next=registry; registry=flag; *out=flag->id; ++created;
    printf("Runtime: event flag '%s' handle=%llu attr=0x%x bits=0x%llx\n",name,
           (unsigned long long)flag->id,attr,(unsigned long long)bits);
    pthread_mutex_unlock(&lock);
    return 0;
}
static int32_t wait_bits(uintptr_t id,uint64_t bits,uint32_t mode,uint64_t *observed,uint32_t *timeout,int block) {
    pthread_mutex_lock(&lock);
    EventFlag *flag=find(id);
    int32_t result=0;
    if (!flag) result=ERR(3);
    else if (!bits || (mode&~UINT32_C(0x33)) || ((mode&3)!=1 && (mode&3)!=2) || (mode&0x30)==0x30) result=ERR(22);
    else if (!(flag->attr&0x20) && flag->active) result=ERR(1);
    else if (matches(flag,bits,mode)) {
        if (observed) *observed=flag->bits;
        consume(flag,bits,mode); ++waits;
    } else if (!block || (timeout && !*timeout)) {
        if (observed) *observed=flag->bits;
        result=block ? ERR(60) : ERR(16);
        if (block) ++timeouts;
    } else {
        FlagWaiter waiter={.bits=bits,.mode=mode,.priority=runtime_thread_priority()};
        pthread_condattr_t attr;
        host_check(pthread_condattr_init(&attr));
        host_check(pthread_condattr_setclock(&attr,WAIT_CLOCK));
        host_check(pthread_cond_init(&waiter.event,&attr));
        host_check(pthread_condattr_destroy(&attr));
        FlagWaiter **slot=&flag->first;
        while (*slot && (!(flag->attr&2) || (*slot)->priority>=waiter.priority)) slot=&(*slot)->next;
        waiter.next=*slot; *slot=&waiter; ++flag->active;
        uint64_t deadline=timeout ? now_ns()+(uint64_t)*timeout*1000 : 0;
        struct timespec end={.tv_sec=(time_t)(deadline/1000000000),.tv_nsec=(long)(deadline%1000000000)};
        while (!waiter.done) {
            int error=timeout ? pthread_cond_timedwait(&waiter.event,&lock,&end) : pthread_cond_wait(&waiter.event,&lock);
            if (error==ETIMEDOUT && !waiter.done) {
                FlagWaiter **link=&flag->first;
                while (*link!=&waiter) link=&(*link)->next;
                *link=waiter.next; waiter.done=1; waiter.result=ERR(60); waiter.observed=flag->bits; ++timeouts;
            } else if (error!=ETIMEDOUT) host_check(error);
        }
        result=waiter.result;
        if (observed) *observed=waiter.observed;
        if (!result) ++waits;
        if (timeout) {
            uint64_t now=now_ns();
            *timeout=result ? 0 : (uint32_t)(now>=deadline ? 0 : (deadline-now)/1000);
        }
        host_check(pthread_cond_destroy(&waiter.event));
        if (!--flag->active && flag->deleted) free(flag);
    }
    pthread_mutex_unlock(&lock);
    return result;
}
static ABI int32_t flag_wait(uintptr_t id,uint64_t bits,uint32_t mode,uint64_t *observed,uint32_t *timeout) {
    return wait_bits(id,bits,mode,observed,timeout,1);
}
static ABI int32_t flag_poll(uintptr_t id,uint64_t bits,uint32_t mode,uint64_t *observed) {
    return wait_bits(id,bits,mode,observed,NULL,0);
}
static ABI int32_t flag_set(uintptr_t id,uint64_t bits) {
    pthread_mutex_lock(&lock);
    EventFlag *flag=find(id);
    if (!flag) { pthread_mutex_unlock(&lock); return ERR(3); }
    flag->bits|=bits; ++signals;
    FlagWaiter **slot=&flag->first;
    while (*slot) {
        FlagWaiter *waiter=*slot;
        if (!matches(flag,waiter->bits,waiter->mode)) { slot=&waiter->next; continue; }
        waiter->observed=flag->bits; consume(flag,waiter->bits,waiter->mode);
        *slot=waiter->next; waiter->done=1;
        host_check(pthread_cond_signal(&waiter->event));
    }
    pthread_mutex_unlock(&lock);
    return 0;
}
static ABI int32_t flag_clear(uintptr_t id,uint64_t mask) {
    pthread_mutex_lock(&lock);
    EventFlag *flag=find(id);
    if (flag) flag->bits&=mask;
    pthread_mutex_unlock(&lock);
    return flag ? 0 : ERR(3);
}
static int32_t wake_all(EventFlag *flag,int32_t error) {
    int32_t count=0;
    while (flag->first) {
        FlagWaiter *waiter=flag->first; flag->first=waiter->next;
        waiter->observed=flag->bits; waiter->result=error; waiter->done=1; ++count;
        host_check(pthread_cond_signal(&waiter->event));
    }
    return count;
}
static ABI int32_t flag_cancel(uintptr_t id,uint64_t bits,int32_t *waiters) {
    pthread_mutex_lock(&lock);
    EventFlag *flag=find(id);
    if (!flag) { pthread_mutex_unlock(&lock); return ERR(3); }
    flag->bits=bits;
    int32_t count=wake_all(flag,ERR(85));
    if (waiters) *waiters=count;
    pthread_mutex_unlock(&lock);
    return 0;
}
static ABI int32_t flag_delete(uintptr_t id) {
    pthread_mutex_lock(&lock);
    EventFlag **slot=&registry;
    while (*slot && (*slot)->id!=id) slot=&(*slot)->next;
    if (!*slot) { pthread_mutex_unlock(&lock); return ERR(3); }
    EventFlag *flag=*slot; *slot=flag->next; flag->deleted=1; ++deleted;
    wake_all(flag,ERR(13));
    if (!flag->active) free(flag);
    pthread_mutex_unlock(&lock);
    return 0;
}
unsigned runtime_event_flag_waiters(uintptr_t id) {
    pthread_mutex_lock(&lock);
    EventFlag *flag=find(id); unsigned count=0;
    if (flag) for (FlagWaiter *w=flag->first;w;w=w->next) ++count;
    pthread_mutex_unlock(&lock);
    return count;
}
uintptr_t runtime_event_flag_resolve(const char *name) {
    static const struct { const char *nid; void *function; } table[]={
        {"BpFoboUJoZU#libkernel",flag_create}, {"8mql9OcQnd4#libkernel",flag_delete},
        {"IOnSvHzqu6A#libkernel",flag_set}, {"7uhBFWRAS60#libkernel",flag_clear},
        {"JTvBflhYazQ#libkernel",flag_wait}, {"9lvj5DjHZiA#libkernel",flag_poll},
        {"PZku4ZrXJqg#libkernel",flag_cancel},
    };
    for (size_t i=0;i<sizeof(table)/sizeof(*table);++i)
        if (!strcmp(name,table[i].nid)) return (uintptr_t)table[i].function;
    return 0;
}
void runtime_event_flag_report(void) {
    pthread_mutex_lock(&lock);
    printf("Runtime: event flags created=%zu, deleted=%zu, waits=%zu, sets=%zu, timeouts=%zu\n",
           created,deleted,waits,signals,timeouts);
    pthread_mutex_unlock(&lock);
}
