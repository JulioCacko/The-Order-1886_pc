/* Resolve the production mount wrappers without a runtime, game or save directory. */
#undef NDEBUG
#include "../src/runtime_savedata.c"
#include <assert.h>

static int file_calls;
const char *runtime_file_user_dir(void) { ++file_calls; return "unused-save-fixture"; }
int runtime_file_mount(const char *guest,const char *host) { (void)guest; (void)host; ++file_calls; return 0; }
void runtime_file_unmount(const char *guest) { (void)guest; ++file_calls; }
#ifdef _WIN32
int compat_remove_tree(const char *path) { (void)path; ++file_calls; return 0; }
#endif
/* Only the shared name/NID translation is substituted; the export table is production. */
uintptr_t runtime_lookup(const RuntimeExport *table,size_t count,const char *symbol) {
    for (size_t i=0;i<count;++i)
        if (!strcmp(table[i].name,symbol)) return (uintptr_t)table[i].function;
    return 0;
}

int main(int argc,char **argv) {
#ifdef _WIN32
    SetErrorMode(SEM_FAILCRITICALERRORS|SEM_NOGPFAULTERRORBOX);
#endif
    assert(argc==2);
    MountResult *unreadable_result=(MountResult *)(uintptr_t)1;
    if (!strcmp(argv[1],"mount2")) {
        typedef int32_t (ABI *MountFn)(const Mount2 *,MountResult *);
        MountFn call=(MountFn)runtime_savedata_resolve("sceSaveDataMount2");
        assert(call);
        assert(call(NULL,unreadable_result)==ERR_PARAMETER);
        assert(call((const Mount2 *)(uintptr_t)1,unreadable_result)==ERR_NOT_INITIALIZED);
        Mount2 invalid_user={.user=-1};
        assert(save_initialize(NULL)==0 && call(&invalid_user,unreadable_result)==ERR_INVALID_USER);
    } else {
        typedef int32_t (ABI *MountFn)(const Mount1 *,MountResult *);
        MountFn call=(MountFn)runtime_savedata_resolve("sceSaveDataMount");
        assert(call);
        assert(call(NULL,unreadable_result)==ERR_PARAMETER);
        assert(call((const Mount1 *)(uintptr_t)1,unreadable_result)==ERR_NOT_INITIALIZED);
        Mount1 invalid_user={.user=-1};
        assert(save_initialize(NULL)==0 && call(&invalid_user,unreadable_result)==ERR_INVALID_USER);
    }
    assert(!file_calls);
    puts("save mount trace test: ok");
    return 0;
}
