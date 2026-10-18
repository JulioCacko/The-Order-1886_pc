/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef ORDER1886_RUNTIME_TROPHIES_H
#define ORDER1886_RUNTIME_TROPHIES_H
#include <stdint.h>

#define RUNTIME_TROPHY_LIMIT 128
#define RUNTIME_TROPHY_INVALID ((int32_t)0x80551604)
/* Generic runtime/kernel EIO, not an invented NpTrophy-specific error code. */
#define RUNTIME_TROPHY_IO_ERROR ((int32_t)0x80020005)
#define RUNTIME_TROPHY_RELATIVE_PATH "trophies/CUSA00076/NPWR06616_00/user-1/unlocks.txt"

typedef struct {
    int64_t unlocked_at[RUNTIME_TROPHY_LIMIT];
    uint32_t flags[4];
    uint32_t count;
} RuntimeTrophySnapshot;

/* Explicit Order profile: CUSA00076, NPWR06616_00, local user 1, service label 0.
 * The caller supplies its validated state root, outside the original game directory. */
int32_t runtime_trophy_configure(const char *state_root, const char *title_id);
/* On storage failure, returns EIO with the last visible in-process snapshot.
 * A post-rename durability failure retains the new visible state and blocks writes until reload. */
int32_t runtime_trophy_snapshot(RuntimeTrophySnapshot *out);
int32_t runtime_trophy_create_context(int32_t *out, int32_t user, uint32_t label, uint64_t options);
int32_t runtime_trophy_create_handle(int32_t *out);
int32_t runtime_trophy_register(int32_t context, int32_t handle, uint64_t options);
int32_t runtime_trophy_validate(int32_t context, int32_t handle);
int32_t runtime_trophy_unlock(int32_t context, int32_t handle, int32_t id, int32_t *platinum);
int32_t runtime_trophy_unlock_state(int32_t context, int32_t handle, uint32_t flags[4], uint32_t *count);
int32_t runtime_trophy_abort_handle(int32_t handle);
int32_t runtime_trophy_destroy_handle(int32_t handle);
int32_t runtime_trophy_destroy_context(int32_t context);
#endif
