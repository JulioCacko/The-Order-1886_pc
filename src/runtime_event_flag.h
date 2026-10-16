#ifndef ORDER1886_RUNTIME_EVENT_FLAG_H
#define ORDER1886_RUNTIME_EVENT_FLAG_H
#include <stdint.h>
uintptr_t runtime_event_flag_resolve(const char *name);
void runtime_event_flag_report(void);
unsigned runtime_event_flag_waiters(uintptr_t handle);
#endif
