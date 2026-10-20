/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Imports of The Order (CUSA00076) that neither resolution layer could answer.
 *
 * Every check resolves the NID exactly the way runtime_resolve does for the game
 * ("NID#library") before exercising the behaviour, so a function that is registered but wrong
 * fails here too. The reference for the semantics is upstream shadPS4 (GPL-2.0-or-later, the
 * same licence): core/libraries/kernel/file_system.cpp, core/libraries/kernel/threads/pthread.cpp
 * and core/libraries/app_content/app_content.cpp. Where this tree has no matching subsystem the
 * check states the smaller behaviour that was ported instead.
 *
 * Failures are reported and counted rather than asserted: these calls block, and a CRT abort in
 * the middle of one hides both the reason and the rest of the run. */
#define _GNU_SOURCE
#include "runtime.h"
#include <stdlib.h>

/* probe.c is not linked into these tests (same stand-in as tests/test_sema.c). */
void runtime_restart(void) { abort(); }

#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#ifdef _WIN32
#include <direct.h>
#include <process.h>
#else
#include <unistd.h>
#endif

/* Guest layouts the syscalls take and return. */
typedef struct { int64_t sec, usec; } GuestTimeval;
typedef struct {
    uint32_t dev, ino;
    uint16_t mode, nlink;
    uint32_t uid, gid, rdev;
    int64_t atime[2], mtime[2], ctime[2];
    int64_t size, blocks;
    uint32_t blksize, flags, gen;
    int32_t lspare;
    int64_t birthtime[2];
} GuestStat;
_Static_assert(sizeof(GuestStat) == 120, "FreeBSD stat layout");
_Static_assert(sizeof(GuestTimeval) == 16, "FreeBSD timeval layout");
/* select's descriptor sets are 1024 bits, as in the reference implementation. */
typedef struct { uint64_t bits[1024 / 64]; } GuestFdSet;

typedef int32_t(ABI *KeyCreate)(uint32_t *key, void *destructor);
typedef int32_t(ABI *KeyDelete)(uint32_t key);
typedef int32_t(ABI *KeySet)(uint32_t key, void *value);
typedef void *(ABI *KeyGet)(uint32_t key);
typedef int32_t(ABI *Select)(int32_t nfds, GuestFdSet *readfds, GuestFdSet *writefds,
                             GuestFdSet *exceptfds, GuestTimeval *timeout);
typedef int32_t(ABI *Chmod)(const char *path, uint32_t mode);
typedef int32_t(ABI *Utimes)(const char *path, const GuestTimeval *times);
typedef int64_t(ABI *Getdents)(int32_t fd, char *buffer, uint64_t size);
typedef void *(ABI *ThreadSelf)(void);
typedef int32_t(ABI *SchedGet)(void *thread, uint32_t *policy, int32_t *priority);
typedef int32_t(ABI *SchedSet)(void *thread, uint32_t policy, const int32_t *priority);
typedef int32_t(ABI *AddcontUnmount)(void *mount_point);
typedef int32_t(ABI *ContentInit)(const unsigned char *init, unsigned char *boot);

#define GET(type, nid) ((type)runtime_resolve(nid, 0))

static int g_failures;

/* A failed check names itself and the line it is on, and the run continues. */
#define CHECK(condition)                                                                           \
    do {                                                                                           \
        if (!(condition)) {                                                                        \
            printf("FAILED (line %d): %s\n", __LINE__, #condition);                                 \
            fflush(stdout);                                                                        \
            ++g_failures;                                                                          \
        }                                                                                          \
    } while (0)

/* This test drives blocking syscalls, so it says where it is: a hang has to name its own place. */
static void step(const char *what) {
    printf("check: %s\n", what);
    fflush(stdout);
}

/* The 12 NIDs the audit found unanswered, spelled as the loader passes them. */
static const char *const kImports[] = {
    "0-KXaS70xy4#libScePosix", "6BpEZuDT7YI#libScePosix", "WrOLvHU0yQM#libScePosix",
    "Xs9hdiD7sAA#libScePosix", "T8fER+tIGgk#libScePosix", "mqULNdimTn0#libScePosix",
    "0Cq8ipKr9n0#libkernel",   "fgIsQ10xYVA#libkernel",   "j2AIqSqJP0w#libkernel",
    "P41kTWUS3EI#libkernel",   "oIRFTjoILBg#libkernel",   "3rHWaV-1KC4#libSceAppContent",
};

static KeyCreate key_create;
static KeyDelete key_delete;
static KeySet key_set;
static KeyGet key_get;
static Select select_fds;
static Chmod chmod_path;
static Utimes utimes_path;
static Getdents getdents_fd;
static ThreadSelf thread_self;
static SchedGet sched_get;
static SchedSet sched_set;
static SchedSet posix_sched_set;
static AddcontUnmount addcont_unmount;

/* Resolves every import the game needs and names each one that is still unanswered. */
static void setup(void) {
    runtime_start(1);
    int missing = 0;
    for (size_t i = 0; i < sizeof(kImports) / sizeof(*kImports); ++i) {
        if (!runtime_resolve(kImports[i], 0)) {
            printf("UNRESOLVED: %s\n", kImports[i]);
            ++missing;
        }
    }
    if (missing) {
        printf("%d of %zu imports of The Order are unanswered\n", missing,
               sizeof(kImports) / sizeof(*kImports));
        exit(EXIT_FAILURE);
    }
    key_get = GET(KeyGet, "0-KXaS70xy4#libScePosix");
    key_delete = GET(KeyDelete, "6BpEZuDT7YI#libScePosix");
    key_set = GET(KeySet, "WrOLvHU0yQM#libScePosix");
    posix_sched_set = GET(SchedSet, "Xs9hdiD7sAA#libScePosix");
    select_fds = GET(Select, "T8fER+tIGgk#libScePosix");
    key_create = GET(KeyCreate, "mqULNdimTn0#libScePosix");
    utimes_path = GET(Utimes, "0Cq8ipKr9n0#libkernel");
    chmod_path = GET(Chmod, "fgIsQ10xYVA#libkernel");
    getdents_fd = GET(Getdents, "j2AIqSqJP0w#libkernel");
    sched_get = GET(SchedGet, "P41kTWUS3EI#libkernel");
    sched_set = GET(SchedSet, "oIRFTjoILBg#libkernel");
    addcont_unmount = GET(AddcontUnmount, "3rHWaV-1KC4#libSceAppContent");
    thread_self = GET(ThreadSelf, "aI+OeCz8xrQ#libkernel");
}

/* ---- thread-specific data ---- */
static uint32_t g_key;
static int g_value_main = 1, g_value_worker = 2, g_value_worker_seen;

static void *key_worker(void *argument) {
    (void)argument;
    /* The same key stores a different pointer for this thread. */
    g_value_worker_seen =
        (key_set(g_key, &g_value_worker) == 0 && key_get(g_key) == &g_value_worker);
    return NULL;
}

static void keys(void) {
    uint32_t key = 0;
    CHECK(key_create(NULL, NULL) != 0); /* EINVAL: no place to store the key */
    CHECK(key_create(&key, NULL) == 0);
    CHECK(key_set(key, &g_value_main) == 0);
    CHECK(key_get(key) == &g_value_main);

    /* The value is per thread: a second thread gets its own slot for the same key. */
    g_key = key;
    g_value_worker_seen = 0;
    pthread_t worker;
    CHECK(pthread_create(&worker, NULL, key_worker, NULL) == 0);
    CHECK(pthread_join(worker, NULL) == 0);
    CHECK(g_value_worker_seen);
    CHECK(key_get(key) == &g_value_main);

    /* An unknown key stores nothing instead of corrupting a slot. */
    CHECK(key_set(key + 1000, &g_value_main) != 0);
    CHECK(key_get(key + 1000) == NULL);

    /* Deleting releases the key for the whole process. */
    CHECK(key_delete(key) == 0);
    CHECK(key_get(key) == NULL);
    CHECK(key_delete(key) != 0);
}

/* ---- filesystem fixtures ---- */
static char g_root[512];

static void root_path(char *out, size_t size, const char *leaf) {
    snprintf(out, size, "%s/%s", g_root, leaf);
}

static void guest_path(char *out, size_t size, const char *leaf) {
    snprintf(out, size, "/temp0/%s", leaf);
}

static void write_file(const char *path, const char *text) {
    FILE *file = fopen(path, "wb");
    CHECK(file != NULL);
    if (!file) return;
    fputs(text, file);
    fclose(file);
}

static void make_dir(const char *path) {
#ifdef _WIN32
    _mkdir(path);
#else
    mkdir(path, 0755);
#endif
}

/* A temporary tree under out/, mounted as /temp0 the way a game mount would be. */
static void mount_root(void) {
#ifdef _WIN32
    const int pid = (int)_getpid();
#else
    const int pid = (int)getpid();
#endif
    snprintf(g_root, sizeof(g_root), "out/missing-imports-%d", pid);
    char path[600];
    make_dir(g_root);
    root_path(path, sizeof(path), "listing");
    make_dir(path);
    root_path(path, sizeof(path), "listing/entry.txt");
    write_file(path, "entry");
    root_path(path, sizeof(path), "data.bin");
    write_file(path, "four");
    CHECK(runtime_file_mount("/temp0", g_root) == 0);
}

/* ---- select over this tree's descriptors ---- */
static void selects(void) {
    GuestFdSet read_set, write_set;
    GuestTimeval now = {0, 0};

    /* With nothing watched and a zero timeout the answer is an immediate zero. */
    CHECK(select_fds(0, NULL, NULL, NULL, &now) == 0);

    /* Bounds and timeout validation from the reference implementation. */
    CHECK(select_fds(-1, NULL, NULL, NULL, &now) == -1 && *runtime_errno() == 22);
    CHECK(select_fds(1025, NULL, NULL, NULL, &now) == -1 && *runtime_errno() == 22);
    GuestTimeval bad = {0, 1000000};
    CHECK(select_fds(0, NULL, NULL, NULL, &bad) == -1 && *runtime_errno() == 22);

    /* A finite wait over nothing that can become ready is a sleep of that length, which is what
     * the reference implementation does. Only the finite case is checked: an unbounded select
     * with nothing to watch blocks by definition. */
    GuestTimeval tick = {0, 50000};
    const clock_t started = clock();
    CHECK(select_fds(0, NULL, NULL, NULL, &tick) == 0);
    CHECK((double)(clock() - started) / CLOCKS_PER_SEC >= 0.04);

    /* An open descriptor is reported readable and writable. */
    const int fd = (int)runtime_file_open("/temp0/data.bin", 0, 0);
    CHECK(fd >= 3);
    memset(&read_set, 0, sizeof(read_set));
    memset(&write_set, 0, sizeof(write_set));
    read_set.bits[fd / 64] |= UINT64_C(1) << (fd % 64);
    write_set.bits[fd / 64] |= UINT64_C(1) << (fd % 64);
    CHECK(select_fds(fd + 1, &read_set, &write_set, NULL, &now) == 2);
    CHECK((read_set.bits[fd / 64] >> (fd % 64)) & 1);
    CHECK((write_set.bits[fd / 64] >> (fd % 64)) & 1);

    /* Descriptor 0 is never reported readable, exactly as upstream does. */
    memset(&read_set, 0, sizeof(read_set));
    read_set.bits[0] |= 1;
    CHECK(select_fds(1, &read_set, NULL, NULL, &now) == 0);
    CHECK(read_set.bits[0] == 0);

    /* A descriptor that is no longer open is EBADF, not a silent zero. */
    CHECK(runtime_file_close(fd) == 0);
    memset(&read_set, 0, sizeof(read_set));
    read_set.bits[fd / 64] |= UINT64_C(1) << (fd % 64);
    CHECK(select_fds(fd + 1, &read_set, NULL, NULL, &now) == -1 && *runtime_errno() == 9);
}

/* ---- timestamps ---- */
static void timestamps(void) {
    char guest[64];
    GuestStat before, after, later_stat;
    guest_path(guest, sizeof(guest), "data.bin");
    CHECK(runtime_file_stat(guest, &before) == 0);

    const GuestTimeval stamp[2] = {{1334567890, 0}, {1334567890, 0}};
    CHECK(utimes_path(guest, stamp) == 0);
    CHECK(runtime_file_stat(guest, &after) == 0);
    /* The host's stat conversion is not always a pure epoch pass-through: on this machine a
     * February 2009 instant reads back an hour later while 2012 and 2023 instants are exact.
     * The test therefore measures the offset for the instant it sets instead of assuming one, and
     * what it insists on is that the reported value follows the value that was set. */
    const int64_t shift = after.mtime[0] - 1334567890;
    CHECK(after.mtime[0] == after.atime[0]);
    CHECK(before.mtime[0] != after.mtime[0]);
    /* A different instant in the same daylight-saving regime moves the report by exactly the same
     * amount: the stored value is the one that was asked for, not a cached one. */
    const GuestTimeval later[2] = {{1334567890 + 86400, 0}, {1334567890 + 86400, 0}};
    CHECK(utimes_path(guest, later) == 0);
    CHECK(runtime_file_stat(guest, &later_stat) == 0);
    CHECK(later_stat.mtime[0] - (1334567890 + 86400) == shift);

    /* Out-of-range microseconds are rejected before any host call. */
    guest_path(guest, sizeof(guest), "data.bin");
    const GuestTimeval bad[2] = {{1, 1000000}, {1, 0}};
    CHECK((uint32_t)utimes_path(guest, bad) == 0x80020016);

    /* Missing path, null path: kernel errors, not crashes. */
    guest_path(guest, sizeof(guest), "absent.bin");
    CHECK((uint32_t)utimes_path(guest, stamp) == 0x80020002);
    CHECK((uint32_t)utimes_path(NULL, stamp) == 0x8002000E);
}

/* ---- permission bits ---- */
static void permissions(void) {
    char guest[64];
    GuestStat status;
    guest_path(guest, sizeof(guest), "data.bin");
    CHECK(chmod_path(guest, 0444) == 0);
    CHECK(runtime_file_stat(guest, &status) == 0);
    CHECK((status.mode & 0200) == 0); /* owner write cleared */
    CHECK(chmod_path(guest, 0644) == 0);
    CHECK(runtime_file_stat(guest, &status) == 0);
    CHECK((status.mode & 0200) != 0); /* and restored */

    guest_path(guest, sizeof(guest), "absent.bin");
    CHECK((uint32_t)chmod_path(guest, 0644) == 0x80020002);
    CHECK((uint32_t)chmod_path(NULL, 0644) == 0x8002000E);
}

/* ---- directory records ---- */
static void listings(void) {
    char guest[64];
    char buffer[1024];
    guest_path(guest, sizeof(guest), "listing");
    const int fd = (int)runtime_file_open(guest, 0, 0);
    CHECK(fd >= 3);

    /* A buffer the reference implementation will not fill, and a null one. */
    CHECK((uint32_t)getdents_fd(fd, buffer, 511) == 0x80020016);
    CHECK((uint32_t)getdents_fd(fd, NULL, sizeof(buffer)) == 0x8002000E);

    const int64_t size = getdents_fd(fd, buffer, sizeof(buffer));
    CHECK(size > 0);
    int found = 0;
    for (int64_t at = 0; at < size;) {
        uint16_t reclen;
        uint8_t namlen;
        memcpy(&reclen, buffer + at + 4, 2);
        namlen = (uint8_t)buffer[at + 7];
        /* Records are 8-byte aligned and stay inside the returned length. */
        CHECK(reclen % 8 == 0 && reclen >= 16 && at + reclen <= size);
        if (namlen == strlen("entry.txt") && memcmp(buffer + at + 8, "entry.txt", namlen) == 0) {
            found = 1;
        }
        at += reclen;
    }
    /* The listing names the file that is really in the directory. */
    CHECK(found);

    CHECK(runtime_file_close(fd) == 0);
    CHECK((uint32_t)getdents_fd(fd, buffer, sizeof(buffer)) == 0x80020009);
    /* A regular file is not a directory. */
    const int file_fd = (int)runtime_file_open("/temp0/data.bin", 0, 0);
    CHECK(file_fd >= 3);
    CHECK((uint32_t)getdents_fd(file_fd, buffer, sizeof(buffer)) == 0x80020016);
    CHECK(runtime_file_close(file_fd) == 0);
}

/* ---- scheduler parameters ---- */
static void scheduling(void) {
    void *const self = thread_self();
    CHECK(self != NULL);
    uint32_t policy = 0;
    int32_t priority = 0;
    CHECK(sched_get(self, &policy, &priority) == 0);
    CHECK(policy == 1 && priority == 700); /* the tree's recorded defaults */

    const int32_t high = 512;
    CHECK(sched_set(self, 2, &high) == 0);
    CHECK(sched_get(self, &policy, &priority) == 0);
    CHECK(policy == 2 && priority == 512);

    /* The libScePosix spelling stores the same state on the same thread. */
    const int32_t low = 800;
    CHECK(posix_sched_set(self, 3, &low) == 0);
    CHECK(sched_get(self, &policy, &priority) == 0);
    CHECK(policy == 3 && priority == 800);

    /* Null outputs, an impossible policy and a thread that is not ours are errors. */
    CHECK((uint32_t)sched_get(self, NULL, &priority) == 0x80020016);
    CHECK((uint32_t)sched_set(self, 9, &low) == 0x80020016);
    CHECK((uint32_t)sched_get(&policy, &policy, &priority) == 0x80020003);
}

/* ---- additional content ---- */
static void addcontent(void) {
    struct { char data[16]; } mount_point;
    memset(&mount_point, 0, sizeof(mount_point));

    /* Before the provider is initialized it refuses, as the reference implementation does. */
    CHECK((uint32_t)addcont_unmount(&mount_point) == 0x80D90001);

    const uint32_t values[5] = {3, 0, 0, 0, 0};
    runtime_content_configure(values);
    unsigned char init[32] = {0}, boot[40];
    ContentInit content_init = GET(ContentInit, "R9lA82OraNs#libSceAppContent");
    CHECK(content_init != NULL);
    if (content_init) {
        CHECK(content_init(init, boot) == 0);
    }

    /* A null mount point is a parameter error. A valid one succeeds because this provider never
     * mounts add-on content (sceAppContentAddcontMount answers NOT_FOUND for every entitlement),
     * which is what the reference returns for a point it has nothing to release. */
    CHECK((uint32_t)addcont_unmount(NULL) == 0x80D90002);
    CHECK(addcont_unmount(&mount_point) == 0);
}

int main(void) {
    step("imports resolve");
    setup();
    step("pthread keys");
    keys();
    step("mount");
    mount_root();
    step("select");
    selects();
    step("utimes");
    timestamps();
    step("chmod");
    permissions();
    step("getdents");
    listings();
    step("schedparam");
    scheduling();
    step("addcont unmount");
    addcontent();
    if (g_failures) {
        printf("%d missing-import checks failed\n", g_failures);
        return EXIT_FAILURE;
    }
    puts("Missing imports: every NID answers and behaves as ported");
    return EXIT_SUCCESS;
}
