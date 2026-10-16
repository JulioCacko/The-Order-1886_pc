/* CPU-only key regression; unrelated service dependencies fail closed. */
#undef NDEBUG
#include "../src/runtime_kernel.c"
#include <assert.h>

int32_t *runtime_errno(void) { abort(); }
void runtime_report(void) { abort(); }
uintptr_t runtime_lookup(const RuntimeExport *table,size_t count,const char *name) {
    (void)table; (void)count; (void)name;
    abort();
}

static uint32_t test_key;
static int markers[2], destructor_calls;
static ABI void destroy_value(void *value) {
    assert(value==&markers[1]);
    ++destructor_calls;
}
static void *key_worker(void *unused) {
    (void)unused;
    assert(key_get(test_key)==NULL);
    assert(posix_key_set(test_key,&markers[1])==0);
    assert(key_get(test_key)==&markers[1]);
    runtime_thread_keys_cleanup();
    assert(key_get(test_key)==NULL);
    return NULL;
}
int main(void) {
    assert(posix_key_create(NULL,NULL)==22 && posix_key_create(&test_key,destroy_value)==0);
    assert(posix_key_set(UINT32_MAX,NULL)==22 && posix_key_delete(UINT32_MAX)==22);
    assert(key_get(test_key)==NULL && posix_key_set(test_key,&markers[0])==0);
    pthread_t worker;
    assert(pthread_create(&worker,NULL,key_worker,NULL)==0 && pthread_join(worker,NULL)==0);
    assert(destructor_calls==1 && key_get(test_key)==&markers[0]);
    assert(posix_key_delete(test_key)==0 && key_get(test_key)==NULL && posix_key_set(test_key,NULL)==22);
    uint32_t replacement;
    assert(posix_key_create(&replacement,NULL)==0 && replacement==test_key && key_get(replacement)==NULL);
    assert(posix_key_delete(replacement)==0 && posix_key_delete(replacement)==22 && destructor_calls==1);
    uint32_t all_keys[256];
    for (size_t i=0;i<256;++i) assert(posix_key_create(&all_keys[i],NULL)==0 && all_keys[i]==i);
    assert(posix_key_create(&replacement,NULL)==35);
    for (size_t i=0;i<256;++i) assert(posix_key_delete(all_keys[i])==0);
    puts("PASS: POSIX key errno, thread isolation, cleanup, reuse, capacity");
    return 0;
}
