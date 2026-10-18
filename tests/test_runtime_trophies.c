/* Exercise the actual trophy ABI wrappers without starting a game or GPU. */
#define main services_fixture_main
#include "test_services.c"
#undef main
#include "runtime_trophies.h"

static void registered(int32_t *context, int32_t *handle) {
    assert(trophy_context(context, 1, 0, 0) == 0);
    assert(trophy_handle(handle) == 0);
    assert(trophy_register(*context, *handle, 0) == 0);
}

static void snapshot(int32_t result) {
    RuntimeTrophySnapshot state;
    (void)runtime_trophy_snapshot(&state);
    printf("{\"result\":%d,\"count\":%u,\"flags\":[%u,%u,%u,%u],\"times\":[",
           result, state.count, state.flags[0], state.flags[1], state.flags[2], state.flags[3]);
    for (unsigned i = 0; i < RUNTIME_TROPHY_LIMIT; ++i)
        printf("%s%lld", i ? "," : "", (long long)state.unlocked_at[i]);
    puts("]}");
}

int main(int argc, char **argv) {
    assert(argc >= 3);
    if (!strcmp(argv[2], "wrong-title")) {
        snapshot(runtime_trophy_configure(argv[1], "CUSA00035"));
        return 0;
    }
    int32_t result = runtime_trophy_configure(argv[1], "CUSA00076");
    if (result || !strcmp(argv[2], "snapshot")) {
        snapshot(result);
        return 0;
    }
    if (!strcmp(argv[2], "hold")) {
        puts("ready"); fflush(stdout);
        (void)getchar();
        return 0;
    }
    int32_t context = 0, handle = 0, platinum = 0;
    assert(trophy_context(&context, 1, 0, 0) == 0);
    assert(trophy_handle(&handle) == 0);
    uint32_t flags[4] = {0}, count = 0;
    assert(trophy_unlock_state(context, handle, flags, &count) == TROPHY_INVALID);
    assert(trophy_register(context, handle, 0) == 0);
    if (!strcmp(argv[2], "unlock")) {
        assert(argc == 4);
        snapshot(trophy_unlock(context, handle, atoi(argv[3]), &platinum));
        return 0;
    }
    assert(trophy_unlock(context, handle, 7, &platinum) == 0);
    assert(platinum == -1);
    assert(trophy_unlock_state(context, handle, flags, &count) == 0);
    assert(flags[0] == (1u << 7) && count == 1);
    if (!strcmp(argv[2], "corrupt-reload")) {
        char path[2048];
        assert(snprintf(path, sizeof(path), "%s/%s", argv[1], RUNTIME_TROPHY_RELATIVE_PATH) > 0);
        FILE *file = fopen(path, "wb");
        assert(file && fputs("corrupt\n", file) >= 0 && fclose(file) == 0);
        assert(runtime_trophy_configure(argv[1], "CUSA00076") == RUNTIME_TROPHY_IO_ERROR);
        assert(trophy_unlock(context, handle, 8, NULL) != 0);
        snapshot(RUNTIME_TROPHY_IO_ERROR);
        return 0;
    }
    assert(!strcmp(argv[2], "lifecycle"));
    assert(trophy_unlock(context, handle, -1, NULL) == TROPHY_INVALID);
    assert(trophy_unlock(context, handle, 128, NULL) == TROPHY_INVALID);
    assert(trophy_unlock(0, handle, 8, NULL) == TROPHY_INVALID);
    assert(trophy_unlock(context, 0, 8, NULL) == TROPHY_INVALID);
    assert(trophy_context(NULL, 1, 0, 0) == TROPHY_INVALID);
    int32_t untouched = 99;
    assert(trophy_context(&untouched, 2, 0, 0) == TROPHY_INVALID && untouched == 99);
    assert(trophy_context(&untouched, 1, 1, 0) == TROPHY_INVALID);
    assert(trophy_context(&untouched, 1, 0, 1) == TROPHY_INVALID);
    assert(trophy_handle(NULL) == TROPHY_INVALID);
    assert(trophy_register(context, handle, 1) == TROPHY_INVALID);
    for (int i = 31; i <= 32; ++i) assert(trophy_unlock(context, handle, i, NULL) == 0);
    assert(trophy_unlock(context, handle, 127, NULL) == 0);
    RuntimeTrophySnapshot before, after;
    assert(runtime_trophy_snapshot(&before) == 0);
    assert(trophy_unlock(context, handle, 7, NULL) == 0);
    assert(runtime_trophy_snapshot(&after) == 0);
    assert(!memcmp(&before, &after, sizeof(before)));
    assert(before.count == 4 && before.unlocked_at[7] > 0);
    assert(trophy_abort_handle(handle) == 0);
    assert(trophy_unlock(context, handle, 8, NULL) == TROPHY_INVALID);
    assert(trophy_destroy_handle(handle) == 0);
    assert(trophy_destroy_handle(handle) == TROPHY_INVALID);
    assert(trophy_destroy_context(handle) == TROPHY_INVALID);
    assert(trophy_destroy_context(context) == 0);
    assert(trophy_destroy_context(context) == TROPHY_INVALID);
    registered(&context, &handle);
    assert(runtime_trophy_configure(argv[1], "CUSA00076") == 0);
    assert(trophy_unlock(context, handle, 8, NULL) == TROPHY_INVALID);
    registered(&context, &handle);
    assert(trophy_unlock_state(context, handle, flags, &count) == 0 && count == 4);
    assert(trophy_unlock_state(context, handle, NULL, &count) == TROPHY_INVALID);
    assert(trophy_unlock_state(context, handle, flags, NULL) == TROPHY_INVALID);
    assert(runtime_trophy_snapshot(&after) == 0);
    assert(!memcmp(&before, &after, sizeof(before)));
    snapshot(0);
    return 0;
}
