// GPU-side assertion failures stop the port with exit code 23.
#include <cstdio>
#include <cstdlib>
#ifdef _WIN32
#include <windows.h>
#include <dbghelp.h>
#endif

namespace {
void CaptureFatalEvidence() {
#ifdef _WIN32
    const char* path = std::getenv("ORDER1886_FATAL_DUMP");
    if (!path || !*path) return;
    void* frames[48]{};
    const auto count = CaptureStackBackTrace(0, 48, frames, nullptr);
    std::fprintf(stderr, "Fatal native stack: image=%p frames=%u\n", GetModuleHandleW(nullptr), unsigned(count));
    for (unsigned i = 0; i < count; ++i) std::fprintf(stderr, "  native[%u]=%p\n", i, frames[i]);
    // An opt-in, small user-process snapshot avoids live-debugger fault handling overhead.
    // CREATE_NEW preserves every existing dump. This does not capture a kernel failure.
    HMODULE library = LoadLibraryExW(L"dbghelp.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!library) return;
    using WriteDump = BOOL(WINAPI*)(HANDLE, DWORD, HANDLE, MINIDUMP_TYPE,
                                   PMINIDUMP_EXCEPTION_INFORMATION,
                                   PMINIDUMP_USER_STREAM_INFORMATION,
                                   PMINIDUMP_CALLBACK_INFORMATION);
    const auto write = reinterpret_cast<WriteDump>(GetProcAddress(library, "MiniDumpWriteDump"));
    HANDLE file = CreateFileA(path, GENERIC_WRITE, 0, nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file != INVALID_HANDLE_VALUE) {
        const BOOL ok = write && write(GetCurrentProcess(), GetCurrentProcessId(), file,
                                      MiniDumpWithThreadInfo, nullptr, nullptr, nullptr);
        std::fprintf(stderr, "Fatal user-process dump: %s (%s)\n", path, ok ? "written" : "failed");
        CloseHandle(file);
    } else {
        std::fprintf(stderr, "Fatal user-process dump: preserving existing or inaccessible path %s\n", path);
    }
    FreeLibrary(library);
#endif
}
} // namespace
#include <stdexcept>
#include "common/assert.h"
#include "common/logging/log.h"

void assert_fail_impl() {
    CaptureFatalEvidence();
    std::fflush(stdout);
    std::fputs("STOP: GPU library assertion failed (see GPU log above)\n", stderr);
    std::_Exit(23);
}

[[noreturn]] void unreachable_impl() {
    assert_fail_impl();
    throw std::runtime_error("Unreachable code");
}

void assert_fail_debug_msg(const char* msg) {
    LOG_CRITICAL(Debug, "Assertion Failed!\n{}", msg);
    assert_fail_impl();
}
