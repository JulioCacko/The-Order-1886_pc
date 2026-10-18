"""Exercise production SRT registration, loading and generation without Vulkan."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.test_order1886_srt_codegen import ROOT, SOURCE, function_body


def registration_harness(source):
    globals_start = source.index('static Xbyak::CodeGenerator g_srt_codegen(')
    globals_end = source.index('namespace Shader {', globals_start)
    globals_and_registration = source[globals_start:globals_end]
    load = function_body(source, 'PFN_SrtWalker RegisterWalkerCode(')
    generate = function_body(source, 'static void GenerateSrtProgram(')
    # Skip the forward declaration when finding the actual handler definition.
    handlers = source[source.index('static void DumpSrtProgram('):]
    handler = function_body(handlers, 'static bool SrtWalkerSignalHandler(')
    return r'''
#include <array>
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <mutex>
#include <xbyak/xbyak.h>
#include "shader_recompiler/ir/passes/srt_walker_cache.h"
using namespace Xbyak::util;
namespace Shader {
using PFN_SrtWalker = void (*)();
struct Info {
    struct {
        PFN_SrtWalker walker_func = nullptr;
        size_t walker_func_size = 0;
        u32 flattened_bufsize_dw = 16;
    } srt_info;
};
}
using Shader::Info;
using Shader::PFN_SrtWalker;
namespace Core {
struct Signals {
    unsigned registrations = 0;
    unsigned priority = 0;
    bool (*handler)(void*, void*) = nullptr;
    static Signals* Instance() { static Signals signals; return &signals; }
    void RegisterAccessViolationHandler(bool (*callback)(void*, void*), u32 order) {
        ++registrations;
        priority = order;
        handler = callback;
    }
};
}
namespace {
static bool SrtWalkerSignalHandler(void*, void*);
}
''' + globals_and_registration + r'''
namespace Shader {
''' + load + r'''
}
namespace {
constexpr u32 NUM_USER_DATA_REGS = 16;
struct PassInfo { std::map<u32, u32> srt_roots{{0, 0}}; u32 dst_off_dw = 0; };
namespace IR { struct Value { explicit Value(u32) {} }; }
static void VisitPointer(IR::Value, u32, PassInfo&, Xbyak::CodeGenerator& code) {
    code.mov(r10d, dword[rdi]);
}
struct Settings { bool IsDumpShaders() const { return false; } } EmulatorSettings;
static void DumpSrtProgram(const Info&, const u8*, size_t) {}
#define ASSERT(expression) assert(expression)
''' + generate + r'''
// Record the dispatcher registration and model decoding this fixture's MOV. The
// range check, speculative-recovery branch, patch and cache invalidation are real.
bool runtime_fault_recover = false;
constexpr unsigned ZYDIS_MAX_OPERAND_COUNT = 2;
constexpr unsigned ZYDIS_MNEMONIC_MOV = 1;
constexpr unsigned ZYDIS_OPERAND_TYPE_REGISTER = 2;
constexpr unsigned ZYDIS_OPERAND_TYPE_MEMORY = 3;
constexpr unsigned ZYDIS_REGISTER_RDI = 4;
constexpr unsigned ZYDIS_REGISTER_R10D = 5;
struct ZydisDecodedInstruction { unsigned mnemonic; size_t length; };
struct ZydisDecodedOperand { unsigned type; struct { unsigned value; } reg; };
using ZyanStatus = int;
#define ZYAN_SUCCESS(status) ((status) == 0)
namespace Common {
static void* GetRip(void* context) { return context; }
struct Decoder {
    static Decoder* Instance() { static Decoder decoder; return &decoder; }
    ZyanStatus decodeInstruction(ZydisDecodedInstruction& instruction,
                                 ZydisDecodedOperand* operands, void*, size_t) {
        instruction = {ZYDIS_MNEMONIC_MOV, 3};
        operands[0] = {ZYDIS_OPERAND_TYPE_REGISTER, {ZYDIS_REGISTER_R10D}};
        operands[1] = {ZYDIS_OPERAND_TYPE_MEMORY, {0}};
        return 0;
    }
};
}
template <typename... Args> void IgnoreLog(Args&&...) {}
constexpr unsigned Render_Recompiler = 0;
#define LOG_WARNING(...) IgnoreLog(__VA_ARGS__)
#define UNREACHABLE_MSG(...) assert(false)
''' + handler + r'''
}
static void Require(bool condition, const char* message) {
    if (!condition) { std::fprintf(stderr, "%s\n", message); std::exit(1); }
}
static void CheckRegistration() {
    auto* signals = Core::Signals::Instance();
    Require(signals->registrations == 1, "SRT fault handler must be registered exactly once");
    Require(signals->priority == 1, "SRT fault handler must follow memory invalidation");
    Require(g_srt_codegen_start == g_srt_codegen.getCode(),
            "SRT fault handler must start at the entire JIT buffer, including earlier code");
    Require(signals->handler != nullptr, "The registered fault callback must exist");
}
int main(int argc, char** argv) {
    Require(argc == 2, "Select cached-first or generated-first");
    const std::array<u8, 4> bytes{0x44, 0x8b, 0x17, 0xc3}; // mov r10d, [rdi]; ret
    // Earlier arena bytes must remain covered even when registration occurs later.
    g_srt_codegen.db(bytes.data(), bytes.size());
    g_srt_codegen.ready();
    Info info;
    PassInfo pass;
    PFN_SrtWalker loaded;
    if (std::strcmp(argv[1], "cached-first") == 0) {
        loaded = Shader::RegisterWalkerCode(bytes.data(), bytes.size());
        CheckRegistration();
        GenerateSrtProgram(info, pass);
    } else {
        GenerateSrtProgram(info, pass);
        CheckRegistration();
        loaded = Shader::RegisterWalkerCode(bytes.data(), bytes.size());
    }
    CheckRegistration();
    Require(info.srt_info.walker_func == loaded, "Identical generated and cached walkers must share code");
    Require(info.srt_info.walker_func_size == bytes.size(), "Generated walker size must be retained");
    Require(g_srt_codegen.getSize() == 2 * bytes.size(), "A byte-cache hit must not grow the JIT arena");
    const auto previous_size = g_srt_codegen.getSize();
    Require(Shader::RegisterWalkerCode(bytes.data(), bytes.size()) == loaded,
            "Repeated cached walker loads must retain byte identity deduplication");
    GenerateSrtProgram(info, pass);
    Require(g_srt_codegen.getSize() == previous_size, "Repeated generation must reuse existing code");
    CheckRegistration();

    auto* signals = Core::Signals::Instance();
    auto* earlier_code = const_cast<u8*>(g_srt_codegen.getCode());
    runtime_fault_recover = true;
    Require(!signals->handler(earlier_code, nullptr), "Speculative faults must remain recoverable");
    Require(std::memcmp(earlier_code, bytes.data(), bytes.size()) == 0,
            "Speculative recovery must not patch the shared walker");
    runtime_fault_recover = false;
    Require(signals->handler(earlier_code, nullptr), "The handler must cover code preceding registration");
    Require(earlier_code[0] == 0x45 && earlier_code[1] == 0x31 && earlier_code[2] == 0xd2,
            "A covered MOV fault must retain the production zero-register patch");
    Require(!signals->handler(const_cast<u8*>(g_srt_codegen.getCurr()), nullptr),
            "The handler must exclude the end of the generated code range");
    Require(Shader::RegisterWalkerCode(bytes.data(), bytes.size()) != loaded,
            "Fault patches must invalidate the existing byte cache");
    CheckRegistration();
}
'''


class SrtFaultRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.environment = os.environ.copy()
        compiler = shutil.which(cls.environment.get('CXX', 'clang++'))
        if os.name == 'nt':
            if compiler is None:
                candidate = (Path(cls.environment.get('MSYS2_ROOT', r'C:\msys64')) /
                             'clang64/bin/clang++.exe')
                if candidate.is_file():
                    compiler = str(candidate)
            if compiler:
                cls.environment['PATH'] = (str(Path(compiler).parent) + os.pathsep +
                                           cls.environment.get('PATH', ''))
        if compiler is None:
            raise AssertionError('clang++ is required for the CPU SRT fault-registration regression')
        temporary = tempfile.TemporaryDirectory(prefix='order1886-srt-fault-')
        cls.addClassCleanup(temporary.cleanup)
        cpp = Path(temporary.name) / 'registration.cpp'
        cls.exe = Path(temporary.name) / ('registration.exe' if os.name == 'nt' else 'registration')
        cpp.write_text(registration_harness(SOURCE.read_text(encoding='utf-8')), encoding='utf-8')
        command = [compiler, '-std=c++23', '-O2', '-UNDEBUG', '-Wall', '-Wextra', '-Werror',
                   '-I' + str(ROOT / 'gpu/third_party/xbyak'), '-I' + str(ROOT / 'gpu/shadps4'),
                   str(cpp), '-o', str(cls.exe)]
        result = subprocess.run(command, capture_output=True, text=True, env=cls.environment)
        if result.returncode:
            raise AssertionError('SRT registration fixture did not compile:\n' + result.stderr)

    def check_order(self, order):
        result = subprocess.run([str(self.exe), order], capture_output=True, text=True,
                                env=self.environment)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_cached_walkers_before_generation_register_the_whole_buffer_once(self):
        self.check_order('cached-first')

    def test_generation_before_cached_walkers_registers_the_whole_buffer_once(self):
        self.check_order('generated-first')


if __name__ == '__main__':
    unittest.main()
