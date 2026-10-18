/* SPDX-License-Identifier: GPL-2.0-or-later
 * Adapted from Jgamrot/bloodborne_pc src/runtime_trophies.c, commit
 * 52e4988f54b0626447563874bf8695633b1a4302: local timestamps and duplicate suppression.
 * Order adds atomic persistence, validation and handle lifetimes. No PSN or save writes. */
#define _POSIX_C_SOURCE 200809L
#include "runtime_trophies.h"
#include <errno.h>
#include <limits.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <io.h>
#include <fcntl.h>
#else
#include <fcntl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

#define HEADER "ORDER1886-TROPHIES 1 CUSA00076 NPWR06616_00 1\n"
enum { MAX_OBJECTS = 32, PATH_BYTES = 2048, STATE_BYTES = 8192 };
typedef struct { int32_t id; int registered; } Context;
typedef struct { int32_t id; int aborted; } Handle;
static pthread_mutex_t trophy_lock = PTHREAD_MUTEX_INITIALIZER;
static int64_t unlocked[RUNTIME_TROPHY_LIMIT];
static Context contexts[MAX_OBJECTS];
static Handle handles[MAX_OBJECTS];
static uint32_t next_id = 1;
static int ready;
static char history_path[PATH_BYTES];
static int check_parents(const char *path, int create);
#ifdef _WIN32
static HANDLE store_lock = INVALID_HANDLE_VALUE;
static int wide_path(const char *path, wchar_t out[PATH_BYTES]) {
    return MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, out, PATH_BYTES) != 0;
}
static FILE *open_file(const char *path, const wchar_t *mode) {
    wchar_t wide[PATH_BYTES];
    if (!wide_path(path, wide)) { errno = EINVAL; return NULL; }
    return _wfopen(wide, mode);
}
#define OPEN_READ(path) open_file(path, L"rb")
#else
static int store_lock = -1;
#define OPEN_READ(path) fopen(path, "rb")
#endif

static FILE *open_temporary(const char *path) {
    if (!check_parents(path, 0)) return NULL;
#ifdef _WIN32
    wchar_t wide[PATH_BYTES];
    if (!wide_path(path, wide)) return NULL;
    HANDLE file = CreateFileW(wide, GENERIC_WRITE, 0, NULL, OPEN_ALWAYS,
                              FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT, NULL);
    if (file == INVALID_HANDLE_VALUE) return NULL;
    BY_HANDLE_FILE_INFORMATION info;
    if (!GetFileInformationByHandle(file, &info) ||
        (info.dwFileAttributes & (FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DIRECTORY)) ||
        info.nNumberOfLinks != 1 ||
        !SetEndOfFile(file)) {
        CloseHandle(file); return NULL;
    }
    int fd = _open_osfhandle((intptr_t)file, _O_WRONLY | _O_BINARY);
    if (fd < 0) { CloseHandle(file); return NULL; }
    FILE *stream = _fdopen(fd, "wb");
    if (!stream) _close(fd);
#else
    int fd = open(path, O_WRONLY | O_CREAT | O_NOFOLLOW, 0600);
    if (fd < 0) return NULL;
    struct stat info;
    if (fstat(fd, &info) || !S_ISREG(info.st_mode) || info.st_nlink != 1 || ftruncate(fd, 0)) {
        close(fd); return NULL;
    }
    FILE *stream = fdopen(fd, "wb");
    if (!stream) close(fd);
#endif
    return stream;
}

#ifndef _WIN32
static int open_parent_directory(const char *path) {
    char parent[PATH_BYTES];
    if (strlen(path) >= sizeof(parent)) return -1;
    strcpy(parent, path);
    char *separator = strrchr(parent, '/');
    if (!separator) return -1;
    if (separator == parent) separator[1] = 0;
    else *separator = 0;
    return open(parent, O_RDONLY | O_DIRECTORY | O_NOFOLLOW);
}

static int sync_parent_directory(const char *path) {
    int directory = open_parent_directory(path);
    if (directory < 0) return 0;
    int ok = fsync(directory) == 0;
    if (close(directory)) ok = 0;
    return ok;
}
#endif

static int check_parents(const char *path, int create) {
    char prefix[PATH_BYTES];
    if (strlen(path) >= sizeof(prefix)) return 0;
    strcpy(prefix, path);
    for (char *p = prefix + 1; *p; ++p) {
        if (*p != '/' && *p != '\\') continue;
#ifdef _WIN32
        if (p == prefix + 2 && prefix[1] == ':') continue;
#endif
        char separator = *p;
        *p = 0;
#ifdef _WIN32
        wchar_t wide[PATH_BYTES];
        if (!wide_path(prefix, wide)) return 0;
        DWORD attributes = GetFileAttributesW(wide);
        if (attributes == INVALID_FILE_ATTRIBUTES && create &&
            (GetLastError() == ERROR_FILE_NOT_FOUND || GetLastError() == ERROR_PATH_NOT_FOUND)) {
            if (!CreateDirectoryW(wide, NULL) && GetLastError() != ERROR_ALREADY_EXISTS) return 0;
            attributes = GetFileAttributesW(wide);
        }
        int ok = attributes != INVALID_FILE_ATTRIBUTES && (attributes & FILE_ATTRIBUTE_DIRECTORY) &&
                 !(attributes & FILE_ATTRIBUTE_REPARSE_POINT);
#else
        struct stat info;
        int found = lstat(prefix, &info) == 0;
        if (!found && create && errno == ENOENT) {
            int created = mkdir(prefix, 0700) == 0;
            if (!created && errno != EEXIST) return 0;
            found = lstat(prefix, &info) == 0;
            if (created && !sync_parent_directory(prefix)) return 0;
        }
        int ok = found && S_ISDIR(info.st_mode);
#endif
        *p = separator;
        if (!ok) return 0;
    }
    return 1;
}

static int lock_store(const char *path) {
    if (!check_parents(path, 0)) return 0;
    if (!strcmp(path, history_path)) {
#ifdef _WIN32
        if (store_lock != INVALID_HANDLE_VALUE) return 1;
#else
        if (store_lock >= 0) return 1;
#endif
    }
    char lock_path[PATH_BYTES];
    if (snprintf(lock_path, sizeof(lock_path), "%s.lock", path) >= (int)sizeof(lock_path)) return 0;
#ifdef _WIN32
    wchar_t wide[PATH_BYTES];
    if (!wide_path(lock_path, wide)) return 0;
    HANDLE acquired = CreateFileW(wide, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ,
                                  NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (acquired == INVALID_HANDLE_VALUE) return 0;
    if (store_lock != INVALID_HANDLE_VALUE) CloseHandle(store_lock);
#else
    int acquired = open(lock_path, O_CREAT | O_RDWR, 0600);
    if (acquired < 0) return 0;
    if (flock(acquired, LOCK_EX | LOCK_NB)) { close(acquired); return 0; }
    if (store_lock >= 0) close(store_lock);
#endif
    store_lock = acquired;
    strcpy(history_path, path);
    return 1;
}

/* Detect incomplete/corrupted local records; this is not an authenticity signature. */
static uint64_t checksum(uint64_t hash, const char *bytes, size_t count) {
    while (count--) { hash ^= (unsigned char)*bytes++; hash *= UINT64_C(1099511628211); }
    return hash;
}

static int number(char **text, unsigned base, uint64_t maximum, uint64_t *out) {
    char *start = *text, *end;
    if (!*start || *start == '-' || *start == '+' || *start == ' ' || *start == '\t') return 0;
    errno = 0;
    unsigned long long value = strtoull(start, &end, (int)base);
    if (errno || end == start || value > maximum) return 0;
    *text = end; *out = value;
    return 1;
}

static int load_state(int64_t result[RUNTIME_TROPHY_LIMIT]) {
    if (!check_parents(history_path, 0)) return 0;
    FILE *file = OPEN_READ(history_path);
    if (!file) return errno == ENOENT;
    char bytes[STATE_BYTES];
    size_t size = fread(bytes, 1, sizeof(bytes), file);
    int ok = !ferror(file) && size < sizeof(bytes) && fgetc(file) == EOF;
    if (fclose(file)) ok = 0;
    if (!ok || size < sizeof(HEADER) - 1 || memchr(bytes, 0, size) ||
        memcmp(bytes, HEADER, sizeof(HEADER) - 1)) return 0;
    uint64_t hash = checksum(UINT64_C(14695981039346656037), bytes, sizeof(HEADER) - 1);
    unsigned count = 0;
    char *line = bytes + sizeof(HEADER) - 1, *end = bytes + size;
    while (line < end) {
        char *newline = memchr(line, '\n', (size_t)(end - line));
        if (!newline) return 0;
        const int final = newline - line >= 4 && !memcmp(line, "END ", 4);
        if (!final) hash = checksum(hash, line, (size_t)(newline - line + 1));
        *newline = 0;
        char *cursor = line + (final ? 4 : 0);
        uint64_t first, second;
        if (!number(&cursor, 10, final ? RUNTIME_TROPHY_LIMIT : RUNTIME_TROPHY_LIMIT - 1, &first) ||
            *cursor++ != ' ' || !number(&cursor, final ? 16 : 10, final ? UINT64_MAX : INT64_MAX, &second) ||
            *cursor) return 0;
        if (final) return newline + 1 == end && first == count && second == hash;
        if (!second || result[first]) return 0;
        result[first] = (int64_t)second;
        ++count;
        line = newline + 1;
    }
    return 0;
}

#ifndef _WIN32
/* 0: no replacement; 1: durable replacement; -1: visible replacement, durability unknown. */
static int replace_state_posix(const char *temporary, const char *target) {
    int directory = open_parent_directory(target);
    if (directory < 0) return 0;
    int result = 0;
    if (rename(temporary, target) == 0) result = fsync(directory) == 0 ? 1 : -1;
    if (close(directory) && result == 1) result = -1;
    return result;
}
#endif

static int persist(const int64_t values[RUNTIME_TROPHY_LIMIT]) {
    if (!check_parents(history_path, 0)) return 0;
    char bytes[STATE_BYTES] = HEADER, temporary[PATH_BYTES];
    size_t used = sizeof(HEADER) - 1;
    unsigned count = 0;
    for (unsigned i = 0; i < RUNTIME_TROPHY_LIMIT; ++i) {
        if (!values[i]) continue;
        int n = snprintf(bytes + used, sizeof(bytes) - used, "%u %lld\n", i, (long long)values[i]);
        if (n < 0 || (size_t)n >= sizeof(bytes) - used) return 0;
        used += (size_t)n; ++count;
    }
    uint64_t hash = checksum(UINT64_C(14695981039346656037), bytes, used);
    int n = snprintf(bytes + used, sizeof(bytes) - used, "END %u %016llx\n", count, (unsigned long long)hash);
    if (n < 0 || (size_t)n >= sizeof(bytes) - used) return 0;
    used += (size_t)n;
    if (snprintf(temporary, sizeof(temporary), "%s.tmp", history_path) >= (int)sizeof(temporary)) return 0;
    FILE *file = open_temporary(temporary);
    if (!file) return 0;
    int ok = fwrite(bytes, 1, used, file) == used && fflush(file) == 0;
#ifdef _WIN32
    if (ok) ok = _commit(_fileno(file)) == 0;
#else
    if (ok) ok = fsync(fileno(file)) == 0;
#endif
    if (fclose(file)) ok = 0;
    /* Do not follow a replaced ancestor even when cleaning up a failed temporary write. */
    if (!check_parents(history_path, 0)) return 0;
#ifdef _WIN32
    wchar_t from[PATH_BYTES], to[PATH_BYTES];
    if (!wide_path(temporary, from) || !wide_path(history_path, to)) return 0;
    if (ok) ok = MoveFileExW(from, to, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) != 0;
    if (!ok) DeleteFileW(from);
#else
    if (ok) ok = replace_state_posix(temporary, history_path);
    if (!ok) unlink(temporary);
#endif
    return ok;
}

int32_t runtime_trophy_configure(const char *state_root, const char *title_id) {
    pthread_mutex_lock(&trophy_lock);
    ready = 0;
    memset(contexts, 0, sizeof(contexts));
    memset(handles, 0, sizeof(handles));
    int32_t result = RUNTIME_TROPHY_INVALID;
    if (state_root && *state_root && title_id && !strcmp(title_id, "CUSA00076")) {
        char path[PATH_BYTES];
        int n = snprintf(path, sizeof(path), "%s/%s", state_root, RUNTIME_TROPHY_RELATIVE_PATH);
        result = RUNTIME_TROPHY_IO_ERROR;
        int64_t loaded[RUNTIME_TROPHY_LIMIT] = {0};
        int loaded_ok = n > 0 && (size_t)n < sizeof(path) && check_parents(path, 1) &&
                        lock_store(path) && load_state(loaded);
#ifndef _WIN32
        if (loaded_ok) loaded_ok = sync_parent_directory(path);
#endif
        if (loaded_ok) {
            memcpy(unlocked, loaded, sizeof(unlocked));
            ready = 1; result = 0;
        }
    }
    pthread_mutex_unlock(&trophy_lock);
    if (result) fprintf(stderr, "Runtime: local trophy store unavailable (error %#x); existing history was not replaced\n", (unsigned)result);
    return result;
}

static Context *context_for(int32_t id) {
    if (id > 0) for (unsigned i = 0; i < MAX_OBJECTS; ++i) if (contexts[i].id == id) return &contexts[i];
    return NULL;
}
static Handle *handle_for(int32_t id) {
    if (id > 0) for (unsigned i = 0; i < MAX_OBJECTS; ++i) if (handles[i].id == id) return &handles[i];
    return NULL;
}
static int32_t valid_pair(int32_t context, int32_t handle, int registered) {
    Context *c = context_for(context);
    Handle *h = handle_for(handle);
    if (!c || !h || h->aborted || (registered && !c->registered)) return RUNTIME_TROPHY_INVALID;
    return ready ? 0 : RUNTIME_TROPHY_IO_ERROR;
}
static void copy_snapshot(RuntimeTrophySnapshot *out) {
    memset(out, 0, sizeof(*out));
    memcpy(out->unlocked_at, unlocked, sizeof(unlocked));
    for (unsigned i = 0; i < RUNTIME_TROPHY_LIMIT; ++i) if (unlocked[i]) {
        out->flags[i / 32] |= UINT32_C(1) << (i % 32); ++out->count;
    }
}
int32_t runtime_trophy_snapshot(RuntimeTrophySnapshot *out) {
    if (!out) return RUNTIME_TROPHY_INVALID;
    pthread_mutex_lock(&trophy_lock);
    copy_snapshot(out);
    int32_t result = ready ? 0 : RUNTIME_TROPHY_IO_ERROR;
    pthread_mutex_unlock(&trophy_lock);
    return result;
}
int32_t runtime_trophy_create_context(int32_t *out, int32_t user, uint32_t label, uint64_t options) {
    if (!out || user != 1 || label || options) return RUNTIME_TROPHY_INVALID;
    pthread_mutex_lock(&trophy_lock);
    int32_t result = ready ? RUNTIME_TROPHY_INVALID : RUNTIME_TROPHY_IO_ERROR;
    for (unsigned i = 0; ready && i < MAX_OBJECTS && next_id <= INT32_MAX; ++i) if (!contexts[i].id) {
        contexts[i].id = (int32_t)next_id++; contexts[i].registered = 0;
        *out = contexts[i].id; result = 0; break;
    }
    pthread_mutex_unlock(&trophy_lock);
    return result;
}
int32_t runtime_trophy_create_handle(int32_t *out) {
    if (!out) return RUNTIME_TROPHY_INVALID;
    pthread_mutex_lock(&trophy_lock);
    int32_t result = ready ? RUNTIME_TROPHY_INVALID : RUNTIME_TROPHY_IO_ERROR;
    for (unsigned i = 0; ready && i < MAX_OBJECTS && next_id <= INT32_MAX; ++i) if (!handles[i].id) {
        handles[i].id = (int32_t)next_id++; handles[i].aborted = 0;
        *out = handles[i].id; result = 0; break;
    }
    pthread_mutex_unlock(&trophy_lock);
    return result;
}
int32_t runtime_trophy_register(int32_t context, int32_t handle, uint64_t options) {
    pthread_mutex_lock(&trophy_lock);
    int32_t result = options ? RUNTIME_TROPHY_INVALID : valid_pair(context, handle, 0);
    if (!result) context_for(context)->registered = 1;
    pthread_mutex_unlock(&trophy_lock);
    return result;
}
int32_t runtime_trophy_validate(int32_t context, int32_t handle) {
    pthread_mutex_lock(&trophy_lock);
    int32_t result = valid_pair(context, handle, 1);
    pthread_mutex_unlock(&trophy_lock);
    return result;
}
int32_t runtime_trophy_unlock(int32_t context, int32_t handle, int32_t id, int32_t *platinum) {
    if (id < 0 || id >= RUNTIME_TROPHY_LIMIT) return RUNTIME_TROPHY_INVALID;
    pthread_mutex_lock(&trophy_lock);
    int32_t result = valid_pair(context, handle, 1);
    int durability_unknown = 0;
    if (!result && !unlocked[id]) {
        int64_t updated[RUNTIME_TROPHY_LIMIT];
        memcpy(updated, unlocked, sizeof(updated));
        time_t now = time(NULL);
        if (now <= 0) result = RUNTIME_TROPHY_IO_ERROR;
        else {
            updated[id] = (int64_t)now;
            int committed = persist(updated);
            if (committed) memcpy(unlocked, updated, sizeof(unlocked));
            if (committed != 1) result = RUNTIME_TROPHY_IO_ERROR;
            if (committed < 0) { ready = 0; durability_unknown = 1; }
        }
    }
    if (!result && platinum) *platinum = -1;
    pthread_mutex_unlock(&trophy_lock);
    if (durability_unknown)
        fprintf(stderr, "Runtime: trophy %d file was replaced but directory durability is unknown; writes disabled until reload\n", id);
    else if (result == RUNTIME_TROPHY_IO_ERROR)
        fprintf(stderr, "Runtime: local trophy operation for %d failed (EIO); check the store status\n", id);
    return result;
}
int32_t runtime_trophy_unlock_state(int32_t context, int32_t handle, uint32_t flags[4], uint32_t *count) {
    if (!flags || !count) return RUNTIME_TROPHY_INVALID;
    pthread_mutex_lock(&trophy_lock);
    int32_t result = valid_pair(context, handle, 1);
    if (!result) {
        RuntimeTrophySnapshot state; copy_snapshot(&state);
        memcpy(flags, state.flags, sizeof(state.flags)); *count = state.count;
    }
    pthread_mutex_unlock(&trophy_lock);
    return result;
}
int32_t runtime_trophy_abort_handle(int32_t handle) {
    pthread_mutex_lock(&trophy_lock);
    Handle *h = handle_for(handle);
    int32_t result = h && !h->aborted ? 0 : RUNTIME_TROPHY_INVALID;
    if (!result) h->aborted = 1;
    pthread_mutex_unlock(&trophy_lock);
    return result;
}
int32_t runtime_trophy_destroy_handle(int32_t handle) {
    pthread_mutex_lock(&trophy_lock);
    Handle *h = handle_for(handle);
    int32_t result = h ? 0 : RUNTIME_TROPHY_INVALID;
    if (h) memset(h, 0, sizeof(*h));
    pthread_mutex_unlock(&trophy_lock);
    return result;
}
int32_t runtime_trophy_destroy_context(int32_t context) {
    pthread_mutex_lock(&trophy_lock);
    Context *c = context_for(context);
    int32_t result = c ? 0 : RUNTIME_TROPHY_INVALID;
    if (c) memset(c, 0, sizeof(*c));
    pthread_mutex_unlock(&trophy_lock);
    return result;
}
