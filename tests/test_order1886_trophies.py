"""Native trophy persistence/ABI checks; no game, Vulkan, or personal state."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
STATE = Path("trophies/CUSA00076/NPWR06616_00/user-1/unlocks.txt")
IO_ERROR = 0x80020005 - (1 << 32)
INVALID = 0x80551604 - (1 << 32)


def production_function(signature):
    source = (ROOT / "src/runtime_trophies.c").read_text(encoding="utf-8")
    start = source.index(signature)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


class TrophyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory(prefix="order-trophy-build-")
        cls.addClassCleanup(cls.build.cleanup)
        cls.environment = os.environ.copy()
        compiler = shutil.which(os.environ.get("CC", "clang"))
        if os.name == "nt":
            compiler = compiler or str(Path(os.environ.get("MSYS2_ROOT", r"C:\msys64")) / "clang64/bin/clang.exe")
            cls.environment["PATH"] = str(Path(compiler).parent) + os.pathsep + cls.environment.get("PATH", "")
        if not compiler or not Path(compiler).is_file():
            raise RuntimeError("clang is required for the native trophy regression")
        cls.compiler = compiler
        cls.exe = Path(cls.build.name) / ("trophies.exe" if os.name == "nt" else "trophies")
        command = [compiler, "-std=c11", "-O2", "-g", "-Wall", "-Wextra", "-Werror", "-pthread",
                   "-I.", "-Isrc", "tests/test_runtime_trophies.c", "src/runtime_trophies.c"]
        if os.name == "nt":
            command += ["src/compat_win.c", "-lws2_32", "-lonecore"]
        subprocess.run(command + ["-o", str(cls.exe)], cwd=ROOT, env=cls.environment, check=True)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="Order trophy ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "user state"

    def run_native(self, action, *arguments):
        result = subprocess.run([str(self.exe), str(self.root), action, *map(str, arguments)],
                                cwd=ROOT, env=self.environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout.splitlines()[-1])

    def test_abi_lifetimes_flags_bounds_and_first_timestamp(self):
        result = self.run_native("lifecycle")
        self.assertEqual(result["count"], 4)
        self.assertEqual(result["flags"], [0x80000080, 1, 0, 0x80000000])
        restarted = self.run_native("snapshot")
        self.assertEqual(restarted["times"], result["times"])

    def test_failed_temporary_write_preserves_disk_and_memory(self):
        before = self.run_native("unlock", 7)
        history = self.root / STATE
        contents = history.read_bytes()
        history.with_name(history.name + ".tmp").mkdir()
        failed = self.run_native("unlock", 9)
        self.assertEqual(failed["result"], IO_ERROR)
        self.assertEqual(failed["times"], before["times"])
        self.assertEqual(history.read_bytes(), contents)

    def test_temporary_hardlink_cannot_modify_another_file(self):
        self.run_native("unlock", 7)
        original = Path(self.temporary.name) / "original-game.bin"
        original.write_bytes(b"original content must stay unchanged")
        history = self.root / STATE
        os.link(original, history.with_name(history.name + ".tmp"))
        self.assertEqual(self.run_native("unlock", 9)["result"], IO_ERROR)
        self.assertEqual(original.read_bytes(), b"original content must stay unchanged")

    def test_second_runtime_cannot_overwrite_an_active_store(self):
        before = self.run_native("unlock", 7)
        process = subprocess.Popen([str(self.exe), str(self.root), "hold"], cwd=ROOT,
                                   env=self.environment, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "ready")
            self.assertEqual(self.run_native("unlock", 9)["result"], IO_ERROR)
        finally:
            process.communicate("\n", timeout=10)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(self.run_native("snapshot")["times"], before["times"])
        self.assertEqual(self.run_native("unlock", 9)["count"], 2)

    @unittest.skipUnless(os.name == "nt", "Windows replacement/handle-sharing contract")
    def test_failed_atomic_replace_preserves_disk_and_memory(self):
        import ctypes
        from ctypes import wintypes
        before = self.run_native("unlock", 7)
        history = self.root / STATE
        contents = history.read_bytes()
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateFileW(str(history), 0x80000000, 3, None, 3, 0x80, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        try:
            failed = self.run_native("unlock", 9)
        finally:
            kernel.CloseHandle(handle)
        self.assertEqual(failed["result"], IO_ERROR)
        self.assertEqual(failed["times"], before["times"])
        self.assertEqual(history.read_bytes(), contents)
        self.assertEqual(self.run_native("unlock", 9)["count"], 2)

    def test_corrupt_history_is_not_silently_reset_or_overwritten(self):
        self.run_native("unlock", 7)
        history = self.root / STATE
        for data in (b"broken\n", history.read_bytes()[:-7], history.read_bytes().replace(b"7 ", b"8 ", 1)):
            with self.subTest(data=data[:40]):
                history.write_bytes(data)
                result = self.run_native("unlock", 9)
                self.assertEqual(result["result"], IO_ERROR)
                self.assertEqual(history.read_bytes(), data)

    def test_failed_reload_keeps_last_good_snapshot_but_blocks_writes(self):
        result = self.run_native("corrupt-reload")
        self.assertEqual(result["result"], IO_ERROR)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["flags"][0], 1 << 7)
        self.assertEqual((self.root / STATE).read_bytes(), b"corrupt\n")

    def test_abandoned_temporary_file_is_not_committed(self):
        before = self.run_native("unlock", 7)
        history = self.root / STATE
        history.with_name(history.name + ".tmp").write_bytes(b"partial write")
        self.assertEqual(self.run_native("snapshot")["times"], before["times"])
        self.assertEqual(self.run_native("unlock", 9)["count"], 2)

    def test_save_title_is_not_a_trophy_profile(self):
        self.assertEqual(self.run_native("wrong-title")["result"], INVALID)
        self.assertFalse(self.root.exists())

    def test_redirected_ancestors_cannot_escape_state_root(self):
        for index, relative in enumerate((Path("trophies"), Path("trophies/CUSA00076/NPWR06616_00"))):
            with self.subTest(ancestor=relative):
                outside = Path(self.temporary.name) / f"outside-game-{index}"
                outside.mkdir()
                sentinel = outside / "original.bin"
                sentinel.write_bytes(b"original game fixture")
                link = self.root / relative
                link.parent.mkdir(parents=True, exist_ok=True)
                if os.name == "nt":
                    subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(link), str(outside)],
                                   check=True, capture_output=True, text=True)
                else:
                    link.symlink_to(outside, target_is_directory=True)
                try:
                    self.assertEqual(self.run_native("unlock", 7)["result"], IO_ERROR)
                    self.assertEqual(list(outside.iterdir()), [sentinel])
                    self.assertEqual(sentinel.read_bytes(), b"original game fixture")
                finally:
                    if os.name == "nt":
                        link.rmdir()  # Remove the owned junction itself, never its target.
                    else:
                        link.unlink()

    def test_posix_directory_commit_order_and_uncertain_snapshot(self):
        # Compile the production POSIX transaction and its actual caller on either host.
        # Only OS calls are simulated: this exercises post-rename failure without a power cut.
        source = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <pthread.h>
#include "runtime_trophies.h"
#define PATH_BYTES 2048
#define O_RDONLY 0
#define O_DIRECTORY 1
#define O_NOFOLLOW 2
static int failure, calls[8], count;
static int fake_open(const char *path, int flags) {
    assert(!strcmp(path, "/state/user-1"));
    assert(flags == (O_RDONLY | O_DIRECTORY | O_NOFOLLOW));
    calls[count++] = 1; return failure == 1 ? -1 : 17;
}
static int fake_rename(const char *from, const char *to) {
    assert(!strcmp(from, "/state/user-1/unlocks.txt.tmp"));
    assert(!strcmp(to, "/state/user-1/unlocks.txt"));
    calls[count++] = 2; return failure == 2 ? -1 : 0;
}
static int fake_fsync(int fd) { assert(fd == 17); calls[count++] = 3; return failure == 3 ? -1 : 0; }
static int fake_close(int fd) { assert(fd == 17); calls[count++] = 4; return failure == 4 ? -1 : 0; }
#define open fake_open
#define rename fake_rename
#define fsync fake_fsync
#define close fake_close
''' + production_function("static int open_parent_directory(") + "\n" + production_function("static int replace_state_posix(") + r'''
static pthread_mutex_t trophy_lock = PTHREAD_MUTEX_INITIALIZER;
static int64_t unlocked[RUNTIME_TROPHY_LIMIT];
static int ready = 1;
static int persisted;
static int32_t valid_pair(int32_t context, int32_t handle, int registered) {
    assert(context == 1 && handle == 2 && registered);
    return ready ? 0 : RUNTIME_TROPHY_IO_ERROR;
}
static int persist(const int64_t values[RUNTIME_TROPHY_LIMIT]) {
    assert(values[7] > 0); return persisted;
}
''' + production_function("int32_t runtime_trophy_unlock(") + r'''
int main(void) {
    for (failure = 0; failure <= 4; ++failure) {
        count = 0;
        const int result = replace_state_posix("/state/user-1/unlocks.txt.tmp", "/state/user-1/unlocks.txt");
        assert(result == (failure == 0 ? 1 : failure >= 3 ? -1 : 0));
        assert(calls[0] == 1);
        if (failure == 1) assert(count == 1);
        else if (failure == 2) assert(count == 3 && calls[1] == 2 && calls[2] == 4);
        else assert(count == 4 && calls[1] == 2 && calls[2] == 3 && calls[3] == 4);
    }
    persisted = -1;
    int32_t platinum = 123;
    assert(runtime_trophy_unlock(1, 2, 7, &platinum) == RUNTIME_TROPHY_IO_ERROR);
    assert(unlocked[7] > 0 && !ready && platinum == 123);
    assert(runtime_trophy_unlock(1, 2, 8, NULL) == RUNTIME_TROPHY_IO_ERROR && !unlocked[8]);
    return 0;
}
'''
        cpp = Path(self.build.name) / "posix-commit.c"
        exe = Path(self.build.name) / ("posix-commit.exe" if os.name == "nt" else "posix-commit")
        cpp.write_text(source, encoding="utf-8")
        subprocess.run([self.compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pthread",
                        "-Isrc", str(cpp), "-o", str(exe)], cwd=ROOT, env=self.environment, check=True)
        result = subprocess.run([str(exe)], cwd=ROOT, env=self.environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("file was replaced but directory durability is unknown", result.stderr)


if __name__ == "__main__":
    unittest.main()
