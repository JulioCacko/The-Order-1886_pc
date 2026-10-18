"""Exercise mapped-range queries against the production VMA table, without a game."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/runtime_memory.c"
HARNESS = r'''
#undef NDEBUG
#include "memory-under-test.c"
#include <assert.h>
int32_t *runtime_errno(void) { abort(); }
uintptr_t runtime_lookup(const RuntimeExport *table, size_t count, const char *name) {
    (void)table; (void)count; (void)name; abort();
}
enum { REGIONS = 1024, HOT = 32, REPEATS = 2000 };
static const uintptr_t test_base = UINT64_C(0x1000000000);
static uintptr_t point(size_t i) { return test_base + i * 2 * PAGE; }
static void fixture(void) {
    vmas = calloc(REGIONS, sizeof(*vmas)); assert(vmas);
    vma_capacity = vma_count = REGIONS;
    write_lock();
    for (size_t i = 0; i < REGIONS; ++i)
        vmas[i] = (Vma){.start=point(i), .end=point(i)+PAGE, .kind=KIND_DIRECT};
    write_unlock();
}
static unsigned long long stamp(void) {
    struct timespec now; assert(timespec_get(&now, TIME_UTC) == TIME_UTC);
    return (unsigned long long)now.tv_sec * 1000000000 + now.tv_nsec;
}
static pthread_barrier_t changed, checked;
static void barrier(pthread_barrier_t *value) {
    int result = pthread_barrier_wait(value);
    assert(result == 0 || result == PTHREAD_BARRIER_SERIAL_THREAD);
}
static void *reader(void *unused) {
    (void)unused;
    for (int i = 0; i < 128; ++i) {
        barrier(&changed);
        assert(runtime_memory_clamp(point(0), 1) == (uint64_t)(i % 2));
        barrier(&checked);
    }
    return NULL;
}
int main(int argc, char **argv) {
    assert(argc == 2); fixture();
    if (!strcmp(argv[1], "writer")) {
        pthread_t thread;
        assert(!pthread_barrier_init(&changed, NULL, 2));
        assert(!pthread_barrier_init(&checked, NULL, 2));
        assert(!pthread_create(&thread, NULL, reader, NULL));
        for (int i = 0; i < 128; ++i) {
            write_lock(); vmas[0].kind = i % 2 ? KIND_DIRECT : KIND_RESERVED; write_unlock();
            barrier(&changed); barrier(&checked);
        }
        assert(!pthread_join(thread, NULL));
        assert(!pthread_barrier_destroy(&changed));
        assert(!pthread_barrier_destroy(&checked));
        puts("writer epochs passed");
    } else if (!strcmp(argv[1], "correctness")) {
        assert(runtime_memory_clamp(0, 1) == 0);
        assert(runtime_memory_clamp(UINTPTR_MAX, 1) == 0);
        assert(runtime_memory_clamp(point(0), 0) == 0);
        assert(runtime_memory_clamp(point(0)+PAGE-1, 3) == 1);
        assert(runtime_memory_clamp(point(0)+PAGE, 1) == 0);
        assert(runtime_memory_clamp(point(0), 1) == 1);
        write_lock(); vmas[0].end = point(0)+1; write_unlock();
        assert(runtime_memory_clamp(point(0), 1) == 1);
        assert(runtime_memory_clamp(point(0)+1, 1) == 0); /* same hash bucket */
        assert(runtime_memory_clamp(point(0), 1) == 1);
        write_lock(); vmas[0].end = point(0)+PAGE; write_unlock();
        write_lock(); vmas[0].kind = KIND_RESERVED;
        assert(runtime_memory_clamp(point(0), 1) == 0); /* odd writer epoch */
        write_unlock();
        assert(runtime_memory_clamp(point(0), 1) == 0);
        write_lock(); vmas[0].kind = KIND_DIRECT; write_unlock();
        assert(runtime_memory_clamp(point(0), 1) == 1);
        write_lock(); vmas[0].end += PAGE; write_unlock();
        assert(runtime_memory_clamp(point(0)+PAGE, 1) == 1); /* cached gap is invalid */
        assert(runtime_memory_clamp(point(0)+PAGE-1, PAGE+2) == PAGE+2);
        write_lock(); vmas[0].end = point(0)+PAGE; write_unlock();
        assert(runtime_memory_clamp(point(0)+PAGE, 1) == 0);
        runtime_disabled_optimizations = 1;
        lookup_calls = 0;
        for (int i = 0; i < 10; ++i) assert(runtime_memory_clamp(point(0), 1) == 1);
        assert(lookup_calls >= 10);
        runtime_disabled_optimizations = 0;
        write_lock(); vmas[0].kind = KIND_RESERVED; write_unlock();
        assert(runtime_memory_clamp(point(0), 1) == 0);
        puts("correctness passed");
    } else {
        const int cold = !strcmp(argv[1], "cold");
        const int repeats = cold ? 1 : REPEATS;
        lookup_calls = 0;
        unsigned long long begin = stamp();
        for (int n = 0; n < repeats; ++n)
            for (int i = 0; i < HOT; ++i)
                assert(runtime_memory_clamp(point(i), 1) == 1);
        printf("{\"queries\":%d,\"lookups\":%llu,\"elapsed_ns\":%llu}\n",
               repeats * HOT, lookup_calls, stamp() - begin);
    }
    free(vmas); return 0;
}
'''


class MappingCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="order-mapping-cache-")
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        # Count actual table searches; the production query/cache code is unchanged.
        source = SOURCE.read_text(encoding="utf-8")
        signature = "static size_t vma_index(uintptr_t a) {"
        if source.count(signature) != 1:
            raise AssertionError("Production lookup definition changed")
        source = source.replace(signature, "static unsigned long long lookup_calls;\n" +
                                signature + " ++lookup_calls;", 1)
        (directory / "memory-under-test.c").write_text(source, encoding="utf-8")
        fixture = directory / "fixture.c"
        fixture.write_text(HARNESS, encoding="utf-8")
        compiler = shutil.which(os.environ.get("CC", "clang"))
        if not compiler and os.name == "nt":
            compiler = str(Path(os.environ.get("MSYS2_ROOT", r"C:\msys64")) / "clang64/bin/clang.exe")
        cls.environment = os.environ.copy()
        cls.environment["PATH"] = str(Path(compiler).parent) + os.pathsep + cls.environment.get("PATH", "")
        cls.exe = directory / ("cache.exe" if os.name == "nt" else "cache")
        command = [compiler, "-std=c11", "-O2", "-UNDEBUG", "-Wall", "-Wextra", "-Werror",
                   "-pthread", "-I" + str(ROOT), "-I" + str(ROOT / "src"), str(fixture)]
        if os.name == "nt":
            command += [str(ROOT / "src/compat_win.c"), "-lonecore", "-lws2_32"]
        result = subprocess.run(command + ["-o", str(cls.exe)], env=cls.environment,
                                capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def run_fixture(self, mode):
        result = subprocess.run([str(self.exe), mode], env=self.environment,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout.strip()

    def test_mapping_boundaries_epoch_changes_and_disabled_optimization(self):
        self.assertEqual(self.run_fixture("correctness"), "correctness passed")

    def test_cache_observes_mapping_epochs_published_by_another_thread(self):
        self.assertEqual(self.run_fixture("writer"), "writer epochs passed")

    def test_one_table_search_per_cold_query(self):
        result = json.loads(self.run_fixture("cold"))
        self.assertEqual(result["lookups"], result["queries"])

    def test_repeated_scene_sized_working_set_avoids_table_walks(self):
        result = json.loads(self.run_fixture("hot"))
        self.assertLess(result["lookups"], result["queries"] // 4)


if __name__ == "__main__":
    unittest.main()
