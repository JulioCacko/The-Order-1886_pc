/* Optional save/dialog call evidence. This does not change API completion or errors. */
#ifndef ORDER1886_RUNTIME_SAVE_TRACE_H
#define ORDER1886_RUNTIME_SAVE_TRACE_H
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#ifdef _WIN32
#include <winsock2.h>
#include <windows.h>
#endif

#define RUNTIME_SAVE_TRACE_LINES 128
typedef struct {
    pthread_mutex_t mutex;
    uint64_t calls, lines, last_poll_ns;
    int has_result;
    int32_t last_result, last_status;
} RuntimeSaveTraceApi;
#define RUNTIME_SAVE_TRACE_INIT {PTHREAD_MUTEX_INITIALIZER,0,0,0,0,0,0}
typedef struct {
    RuntimeSaveTraceApi *api;
    const char *name;
    uint64_t id, start_ns, thread;
    int paired, poll;
} RuntimeSaveTraceCall;

static inline uint64_t runtime_save_trace_ns(void) {
#ifdef _WIN32
    LARGE_INTEGER ticks, frequency;
    if (!QueryPerformanceCounter(&ticks) || !QueryPerformanceFrequency(&frequency)) return 0;
    return (uint64_t)(ticks.QuadPart/frequency.QuadPart)*UINT64_C(1000000000) +
           (uint64_t)(ticks.QuadPart%frequency.QuadPart)*UINT64_C(1000000000)/frequency.QuadPart;
#else
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC,&value)) return 0;
    return (uint64_t)value.tv_sec*UINT64_C(1000000000)+(uint64_t)value.tv_nsec;
#endif
}
static inline uint64_t runtime_save_trace_thread(void) {
#ifdef _WIN32
    return GetCurrentThreadId();
#else
    return (uint64_t)(uintptr_t)pthread_self();
#endif
}
static inline int runtime_save_trace_enabled(void) {
    const char *enabled=getenv("ORDER1886_DIAG_SAVE");
    return enabled && enabled[0]=='1';
}
static inline RuntimeSaveTraceCall runtime_save_trace_begin(RuntimeSaveTraceApi *api,
                                                           const char *name, int poll,
                                                           const char *format, ...) {
    RuntimeSaveTraceCall call={0};
    if (!runtime_save_trace_enabled()) return call;
    call.api=api; call.name=name; call.poll=poll;
    call.start_ns=runtime_save_trace_ns(); call.thread=runtime_save_trace_thread();
    pthread_mutex_lock(&api->mutex);
    call.id=++api->calls;
    const int sample=!poll || call.id==1 ||
                     (call.start_ns>=api->last_poll_ns &&
                      call.start_ns-api->last_poll_ns>=UINT64_C(1000000000));
    if (sample && api->lines+2<=RUNTIME_SAVE_TRACE_LINES) {
        api->lines+=2; api->last_poll_ns=call.start_ns; call.paired=1;
    }
    pthread_mutex_unlock(&api->mutex);
    if (call.paired) {
        char arguments[512];
        va_list args; va_start(args,format); vsnprintf(arguments,sizeof(arguments),format,args); va_end(args);
        printf("SaveTrace: api=%s call=%llu phase=enter thread=%llu monotonic_ns=%llu %s\n",
               name,(unsigned long long)call.id,(unsigned long long)call.thread,
               (unsigned long long)call.start_ns,arguments);
        fflush(stdout);
    }
    return call;
}
static inline int32_t runtime_save_trace_end(RuntimeSaveTraceCall call, int32_t result,
                                            int32_t status) {
    if (!call.api) return result;
    const uint64_t end_ns=runtime_save_trace_ns();
    RuntimeSaveTraceApi *api=call.api;
    int emit=call.paired;
    pthread_mutex_lock(&api->mutex);
    const int changed=!api->has_result || api->last_result!=result || api->last_status!=status;
    /* A sampled status change can have a return record without an enter record. */
    if (!emit && call.poll && changed && api->lines<RUNTIME_SAVE_TRACE_LINES) {
        ++api->lines; emit=1;
    }
    api->has_result=1; api->last_result=result; api->last_status=status;
    pthread_mutex_unlock(&api->mutex);
    if (emit) {
        printf("SaveTrace: api=%s call=%llu phase=return thread=%llu monotonic_ns=%llu "
               "duration_ns=%llu result=0x%08x status=%d sample=%s\n",
               call.name,(unsigned long long)call.id,(unsigned long long)call.thread,
               (unsigned long long)end_ns,(unsigned long long)(end_ns-call.start_ns),
               (uint32_t)result,status,call.paired ? "paired" : "change");
        fflush(stdout);
    }
    return result;
}
#endif
