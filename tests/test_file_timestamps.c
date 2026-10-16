/* Exercise real guest-fd timestamp changes on isolated host files. */
#undef NDEBUG
#include "../src/runtime_file.c"
#include <assert.h>
#include <time.h>

typedef struct { int64_t sec, usec; } TestTimeval;
_Static_assert(sizeof(TestTimeval)==16 && offsetof(TestTimeval,usec)==8,"guest timeval ABI");
typedef int64_t (ABI *TimestampCall)(int,const TestTimeval *);
static int32_t guest_errno;
int32_t *runtime_errno(void) { return &guest_errno; }
/* EBADF/EINVAL/EROFS have the same host and guest values on the test targets. */
int32_t runtime_guest_errno(int error) { return error; }
/* Link the production runtime.c resolver without booting unrelated subsystems.
 * These seams must never be called by runtime_file_resolve in this contract. */
#define UNUSED_RESOLVER(name) uintptr_t name(const char *nid) { (void)nid; abort(); }
UNUSED_RESOLVER(runtime_mutex_resolve)
UNUSED_RESOLVER(runtime_thread_resolve)
UNUSED_RESOLVER(runtime_content_resolve)
UNUSED_RESOLVER(runtime_time_resolve)
UNUSED_RESOLVER(runtime_sema_resolve)
UNUSED_RESOLVER(runtime_event_flag_resolve)
UNUSED_RESOLVER(runtime_rwlock_resolve)
UNUSED_RESOLVER(runtime_memory_resolve)
UNUSED_RESOLVER(runtime_kernel_resolve)
UNUSED_RESOLVER(runtime_services_resolve)
UNUSED_RESOLVER(runtime_ajm_resolve)
UNUSED_RESOLVER(runtime_videodec_resolve)
UNUSED_RESOLVER(runtime_audio_resolve)
UNUSED_RESOLVER(runtime_pad_resolve)
UNUSED_RESOLVER(runtime_rtc_resolve)
UNUSED_RESOLVER(runtime_savedata_resolve)
UNUSED_RESOLVER(ps4gpu_resolve)
#undef UNUSED_RESOLVER
#define UNUSED_REPORT(name) void name(void) { abort(); }
UNUSED_REPORT(runtime_thread_report)
UNUSED_REPORT(runtime_mutex_report)
UNUSED_REPORT(runtime_rwlock_report)
UNUSED_REPORT(runtime_sema_report)
UNUSED_REPORT(runtime_event_flag_report)
UNUSED_REPORT(runtime_content_report)
UNUSED_REPORT(runtime_memory_report)
UNUSED_REPORT(runtime_ajm_report)
UNUSED_REPORT(runtime_audio_report)
UNUSED_REPORT(runtime_pad_report)
UNUSED_REPORT(runtime_savedata_report)
#undef UNUSED_REPORT
typedef struct { int64_t access_ns, modify_ns; } HostTimes;
static HostTimes times_at(const char *path) {
#ifdef _WIN32
    HANDLE file=CreateFileA(path,FILE_READ_ATTRIBUTES,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,
                            NULL,OPEN_EXISTING,FILE_FLAG_BACKUP_SEMANTICS,NULL);
    assert(file!=INVALID_HANDLE_VALUE);
    FILETIME access,modify;
    assert(GetFileTime(file,NULL,&access,&modify));
    assert(CloseHandle(file));
    const uint64_t a=((uint64_t)access.dwHighDateTime<<32)|access.dwLowDateTime;
    const uint64_t m=((uint64_t)modify.dwHighDateTime<<32)|modify.dwLowDateTime;
    return (HostTimes){(int64_t)(a-UINT64_C(116444736000000000))*100,
                       (int64_t)(m-UINT64_C(116444736000000000))*100};
#else
    struct stat info;
    assert(!stat(path,&info));
    return (HostTimes){(int64_t)info.st_atim.tv_sec*1000000000+info.st_atim.tv_nsec,
                       (int64_t)info.st_mtim.tv_sec*1000000000+info.st_mtim.tv_nsec};
#endif
}
static int64_t wall_ns(void) {
    struct timespec value;
    assert(timespec_get(&value,TIME_UTC)==TIME_UTC);
    return (int64_t)value.tv_sec*1000000000+value.tv_nsec;
}
static void same_times(HostTimes a,HostTimes b) {
    assert(a.access_ns==b.access_ns && a.modify_ns==b.modify_ns);
}
int main(int argc,char **argv) {
#ifdef _WIN32
    SetErrorMode(SEM_FAILCRITICALERRORS|SEM_NOGPFAULTERRORBOX);
#endif
    assert(argc==3);
    TimestampCall kernel=(TimestampCall)runtime_file_resolve("NLq2b1jOaN0#libkernel");
    TimestampCall posix_kernel=(TimestampCall)runtime_file_resolve("+0EDo7YzcoU#libkernel");
    TimestampCall posix_api=(TimestampCall)runtime_file_resolve("+0EDo7YzcoU#libScePosix");
    if (!kernel || !posix_kernel || !posix_api) {
        fputs("MISSING EXPORT: sceKernelFutimes / futimes\n",stderr);
        return 42;
    }
    assert(!strcmp(runtime_symbol("NLq2b1jOaN0#libkernel"),"sceKernelFutimes"));
    assert(!strcmp(runtime_symbol("+0EDo7YzcoU#libkernel"),"futimes"));
    assert(!strcmp(runtime_symbol("+0EDo7YzcoU#libScePosix"),"futimes"));
    assert(kernel==(TimestampCall)sce_futimes);
    assert(posix_kernel==(TimestampCall)posix_futimes && posix_api==posix_kernel);
    runtime_file_configure(argv[1],argv[2]);
    char guard_path[1024],target[1024],original[1024],directory[1024];
    snprintf(guard_path,sizeof(guard_path),"%s/data/host-guard.bin",argv[2]);
    snprintf(target,sizeof(target),"%s/data/timestamp-save.bin",argv[2]);
    snprintf(original,sizeof(original),"%s/original.bin",argv[1]);
    snprintf(directory,sizeof(directory),"%s/data/directory",argv[2]);
    FILE *guard=fopen(guard_path,"wb"); assert(guard);
    assert(fwrite("guard",1,5,guard)==5 && !fflush(guard));
    HostTimes guard_before=times_at(guard_path);
    int fd=(int)runtime_file_open("/data/timestamp-save.bin",0x202,0644);
    assert(fd>=3 && host_fd(fd)!=fd); // Occupied host fd makes a guest/host mixup observable.
    assert(runtime_file_write(fd,"owned-save",10)==10 && !do_fsync(fd));
    const TestTimeval first[2]={{1600000000,123456},{1600000100,654321}};
    assert(kernel(fd,first)==0);
    HostTimes changed=times_at(target);
    assert(changed.access_ns==INT64_C(1600000000123456000));
    assert(changed.modify_ns==INT64_C(1600000100654321000));
    same_times(guard_before,times_at(guard_path));
    const TestTimeval mixed[2]={{0,0},{1600000100,999999}};
    assert(kernel(fd,mixed)==0);
    changed=times_at(target);
    assert(changed.access_ns==0 && changed.modify_ns==INT64_C(1600000100999999000));
    const TestTimeval second[2]={{1600000200,234567},{1600000300,765432}};
    guest_errno=77;
    assert(posix_api(fd,second)==0 && guest_errno==77);
    changed=times_at(target);
    assert(changed.access_ns==INT64_C(1600000200234567000));
    assert(changed.modify_ns==INT64_C(1600000300765432000));
    const TestTimeval invalid[3][2]={{{1600000000,-1},{1600000000,0}},
                                    {{1600000000,0},{1600000000,1000000}},
                                    {{1600000000,0},{1600000000,1073741823}}};
    for (int i=0;i<3;++i) {
        assert(kernel(fd,invalid[i])==(int32_t)0x80020016);
        guest_errno=0; assert(posix_api(fd,invalid[i])==-1 && guest_errno==22);
        same_times(changed,times_at(target));
    }
    guest_errno=91;
    assert(kernel(-1,first)==(int32_t)0x80020009 && guest_errno==91);
    assert(posix_kernel(MAX_FILES+10,first)==-1 && guest_errno==9);
    const int64_t before=wall_ns();
    assert(kernel(fd,NULL)==0);
    const int64_t after=wall_ns();
    changed=times_at(target);
    assert(changed.access_ns>=before && changed.access_ns<=after);
    assert(changed.modify_ns>=before && changed.modify_ns<=after);
    assert(!runtime_file_close(fd));
    assert(kernel(fd,first)==(int32_t)0x80020009);
    guest_errno=0; assert(posix_api(fd,NULL)==-1 && guest_errno==9);
    fd=(int)runtime_file_open("/data/timestamp-save.bin",0,0);
    assert(fd>=3 && posix_kernel(fd,second)==0); // Metadata changes are valid on a read-only fd.
    assert(!runtime_file_close(fd));
    changed=times_at(target);
    assert(changed.access_ns==INT64_C(1600000200234567000));
    assert(changed.modify_ns==INT64_C(1600000300765432000));
    assert(!path_op("/data/directory",0,0755));
    int dir=(int)runtime_file_open("/data/directory",0x20000,0);
    assert(dir>=3 && kernel(dir,first)==0 && !runtime_file_close(dir));
    HostTimes dir_times=times_at(directory);
    assert(dir_times.access_ns==INT64_C(1600000000123456000));
    assert(dir_times.modify_ns==INT64_C(1600000100654321000));
    const char *game_paths[]={"/app0/original.bin","/hostapp/original.bin","original.bin"};
    const HostTimes original_before=times_at(original);
    for (unsigned i=0;i<sizeof(game_paths)/sizeof(*game_paths);++i) {
        int game=(int)runtime_file_open(game_paths[i],0,0); assert(game>=3);
        assert(kernel(game,first)==(int32_t)0x8002001e);
        guest_errno=0; assert(posix_api(game,NULL)==-1 && guest_errno==30);
        assert(!runtime_file_close(game));
        same_times(original_before,times_at(original));
    }
    same_times(guard_before,times_at(guard_path));
    assert(!fclose(guard));
    puts("Guest file timestamps PASS: microseconds, NULL-now, adapters, fd map, directories and readonly game");
    return 0;
}
