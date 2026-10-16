"""Exercise the production SRT emission boundary without starting Vulkan or a game."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "gpu/shadps4/shader_recompiler/ir/passes/flatten_extended_userdata_pass.cpp"


def function_body(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


def harness(source):
    # Only dependency computation is substituted. The emission transaction, pointer push,
    # address masking, pointer load and pop below are copied verbatim from production.
    transaction = function_body(source, "static bool TryComputeOffset(")
    push = function_body(source, "static inline bool PushPtr(")
    pop = function_body(source, "static inline void PopPtr(")
    shift_left = function_body(source, "static bool EmitComputeOffsetShiftLeftLogical32(")
    return r'''
#include <cassert>
#include <cstdint>
#include <xbyak/xbyak.h>
using namespace Xbyak::util;
struct PassInfo {};
namespace IR {
struct Value {
    bool immediate;
    uint32_t value;
    bool fail = false;
    bool IsImmediate() const { return immediate; }
    uint32_t U32() const { return value; }
};
struct Inst {
    Value args[2];
    Value Arg(unsigned index) const { return args[index]; }
    bool AreAllArgsImmediates() const { return args[0].immediate && args[1].immediate; }
};
}
static bool ComputeOffset(Xbyak::CodeGenerator& c, Xbyak::Reg32 reg, PassInfo&,
                          const IR::Value& value) {
    c.mov(reg, value.value);
    if (value.fail) {
        // Model failure after a dependency has already emitted a temporary save.
        c.push(rdx);
        return false;
    }
    return true;
}
// Match the production helper's assertion and failure-cleanup macros.
#define ASSERT(expression) assert(expression)
#define ABORT_ON_FAILURE(expression) if (!(expression)) { return false; }
#define POP_ABORT_ON_FAILURE(expression) if (!(expression)) { c.add(rsp, 8); return false; }
''' + transaction + "\n" + push + "\n" + pop + "\n" + shift_left + r'''
using Walker = uint32_t (__attribute__((sysv_abi)) *)(const uint32_t*);
int main() {
    PassInfo pass;
    Xbyak::CodeGenerator code;
    code.nop();
    const auto unchanged = code.getSize();
    assert(!TryComputeOffset(code, r10d, pass, {false, 17, true}));
    assert(code.getSize() == unchanged);
    assert(!PushPtr(code, pass, {false, 23, true}));
    assert(code.getSize() == unchanged);

    alignas(8) uint32_t child[] = {123, 456};
    alignas(8) uint32_t roots[6]{};
    const uintptr_t child_address = reinterpret_cast<uintptr_t>(child);
    roots[0] = roots[2] = uint32_t(child_address);
    roots[1] = roots[3] = uint32_t(child_address >> 32);
    roots[4] = 9;
    assert(PushPtr(code, pass, {true, 0}));
    code.mov(eax, dword[rdi]);
    PopPtr(code);
    code.add(eax, dword[rdi + 16]);
    code.ret();
    code.ready();
    assert(code.getCode<Walker>()(roots) == 132);

    // A dynamic offset still reaches the selected root and restores the caller's base.
    Xbyak::CodeGenerator dynamic;
    assert(PushPtr(dynamic, pass, {false, 2}));
    dynamic.mov(eax, dword[rdi + 4]);
    PopPtr(dynamic);
    dynamic.add(eax, dword[rdi + 16]);
    dynamic.ret();
    dynamic.ready();
    assert(dynamic.getCode<Walker>()(roots) == 465);

    Xbyak::CodeGenerator offset;
    assert(TryComputeOffset(offset, eax, pass, {false, 41}));
    offset.ret();
    offset.ready();
    assert(offset.getCode<Walker>()(roots) == 41);

    const auto check_shift = [&](IR::Value left, IR::Value right, uint32_t expected) {
        Xbyak::CodeGenerator shift;
        IR::Inst instruction{{left, right}};
        assert(EmitComputeOffsetShiftLeftLogical32(shift, eax, pass, &instruction));
        shift.ret();
        shift.ready();
        assert(shift.getCode<Walker>()(roots) == expected);
    };
    check_shift({true, 1}, {false, 3}, 8);
    check_shift({true, 4}, {false, 3}, 32);
    check_shift({false, 3}, {true, 2}, 12);
    check_shift({false, 3}, {false, 2}, 12);
    check_shift({true, 1}, {false, 35}, 8);
}
'''


def bounded_readconst_harness(source):
    upper_bound = function_body(source, "static u64 ReadConstIndexUpperBound(")
    byte_span = function_body(source, "static std::optional<u32> ReadConstByteSpan(")
    return r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <optional>
#include <span>
#include "shader_recompiler/resource.h"
namespace Common::Log {
bool ShouldLog(Level) { return true; }
void Write(std::string_view, Level, const char*, int, const char*, std::string&& message) {
    std::fprintf(stderr, "%s\n", message.c_str());
    std::fflush(stderr);
}
}
void assert_fail_impl() { std::_Exit(86); }
[[noreturn]] void unreachable_impl() { std::_Exit(86); }
namespace Shader::IR {
enum class Opcode { Phi, ReadConstBuffer, IAdd32, IMul32, ShiftRightLogical32,
                    ShiftLeftLogical32, BitwiseAnd32, UMin32, UMax32 };
struct Inst;
struct Value {
    const Inst* inst = nullptr;
    u32 immediate = 0;
    Value(u32 value) : immediate(value) {}
    Value(const Inst& node) : inst(&node) {}
    bool IsImmediate() const { return !inst; }
    u32 U32() const { assert(!inst); return immediate; }
    const Inst* TryInst() const { return inst; }
};
struct Inst {
    Opcode opcode;
    std::array<Value, 2> args;
    Opcode GetOpcode() const { return opcode; }
    Value Arg(size_t index) const { return args[index]; }
};
}
namespace Shader::Optimization {
''' + upper_bound + "\n" + byte_span + r'''
}
struct FixtureInfo {
    std::array<u32, 8> words{};
    u64 pgm_hash = 1;
    std::string_view hw_stage = "cpu";
    std::span<const u32> FlatUserData() const { return words; }
    u64 ProgramBase() const { return 0; }
};
int main(int argc, char**) {
    using namespace Shader;
    using namespace Shader::IR;
    using namespace Shader::Optimization;
    const Inst changing_phi{Opcode::Phi, {0u, 1u}};
    assert(ReadConstIndexUpperBound(Value{changing_phi}) == UINT32_MAX);
    const Inst light_record{Opcode::ReadConstBuffer, {Value{changing_phi}, 10u}};
    const Inst high_half{Opcode::ShiftRightLogical32, {Value{light_record}, 16u}};
    const Inst byte_stride{Opcode::IMul32, {Value{high_half}, 64u}};
    const Inst dword_stride{Opcode::ShiftRightLogical32, {Value{byte_stride}, 2u}};
    const Inst matrix_word{Opcode::IAdd32, {Value{dword_stride}, 31u}};
    const auto span = ReadConstByteSpan(Value{matrix_word});
    assert(span && *span == 4194368);
    // All possible high-half values, including distinct loop iterations, fit the proof.
    for (u32 index = 0; index <= 65535; ++index) {
        const u64 address = u64(index) * 64 + 31 * 4;
        assert(address + 4 <= *span);
    }
    const Inst overflow_add{Opcode::IAdd32, {UINT32_MAX, 1u}};
    const Inst overflow_mul{Opcode::IMul32, {65536u, 65536u}};
    const Inst overflow_shift{Opcode::ShiftLeftLogical32, {UINT32_MAX, 1u}};
    const Inst out_of_width_shift{Opcode::ShiftRightLogical32, {1u, 32u}};
    for (const auto* node : {&overflow_add, &overflow_mul, &overflow_shift, &out_of_width_shift}) {
        assert(ReadConstIndexUpperBound(Value{*node}) == UINT32_MAX);
        assert(!ReadConstByteSpan(Value{*node}));
    }
    const Inst masked{Opcode::BitwiseAnd32, {Value{changing_phi}, 63u}};
    const Inst bounded_add{Opcode::IAdd32, {Value{masked}, 7u}};
    assert(ReadConstByteSpan(Value{bounded_add}) == 284);
    const Inst minimum{Opcode::UMin32, {Value{changing_phi}, 256u}};
    assert(ReadConstByteSpan(Value{minimum}) == 1028);
    assert(ReadConstByteSpan(Value{0u}) == 4);
    assert(!ReadConstByteSpan(Value{changing_phi}));

    FixtureInfo info;
    BufferResource resource;
    resource.buffer_type = BufferType::ReadConst;
    resource.readconst_size_bytes = *span;
    resource.sharp_fetch.load_mask = 3;
    resource.sharp_fetch.offsets.fill(UNKNOWN_LOCATION);
    resource.sharp_fetch.offsets[0] = 0;
    resource.sharp_fetch.offsets[1] = 1;
    if (argc > 1) {
        info.pgm_hash = 0x804aeead;
        info.words[0] = 0xdeadbeef;
        info.words[1] = 0xa5a50100;
        resource.GetSharp(info);
        return 99; // An invalid pointer must still assert, never become a null buffer.
    }
    info.words[0] = 0x123400;
    info.words[1] = 0x10;
    const auto first = resource.GetSharp(info);
    assert(!resource.IsSpecial() && first.base_address == 0x1000123400ULL);
    assert(first.GetSize() == *span && first.stride == 0);
    info.words[0] = 0x567800;
    const auto refreshed = resource.GetSharp(info);
    assert(refreshed.base_address == 0x1000567800ULL);
    assert(first.base_address != refreshed.base_address);
    assert(refreshed.GetSize() == *span && !resource.is_formatted);
    // InfoPersistent stores its inline resource tables as bytes. All pointer-fetch
    // locations and the proven requested extent must survive that cache round trip.
    std::array<std::byte, sizeof(BufferResource)> bytes;
    std::memcpy(bytes.data(), &resource, sizeof(resource));
    BufferResource restored;
    std::memcpy(&restored, bytes.data(), bytes.size());
    assert(restored.buffer_type == BufferType::ReadConst);
    assert(restored.readconst_size_bytes == *span);
    assert(restored.sharp_fetch == resource.sharp_fetch);
    assert(restored.GetSharp(info).base_address == refreshed.base_address);

    assert(FitsReadConstStorageRange(4096, 0, 4096));
    assert(FitsReadConstStorageRange(4000, 96, 4096));
    assert(!FitsReadConstStorageRange(4000, 97, 4096));
    assert(!FitsReadConstStorageRange(4, 1, 4096));
    assert(!FitsReadConstStorageRange(4, 256, 4096));
    assert(!FitsReadConstStorageRange(4097, 0, 4096));
    assert(!FitsReadConstStorageRange(0, 0, 4096));
    assert(!FitsReadConstStorageRange(UINT64_MAX, 1, 4096));
}
'''


class SrtCodegenTests(unittest.TestCase):
    def test_bounded_dynamic_readconst_and_pointer_refresh(self):
        compiler = shutil.which(os.environ.get("CXX", "clang++"))
        environment = os.environ.copy()
        toolchain = Path(environment.get("MSYS2_ROOT", r"C:\msys64")) / "clang64"
        if os.name == "nt":
            if compiler is None:
                candidate = toolchain / "bin/clang++.exe"
                if candidate.is_file():
                    compiler = str(candidate)
            if compiler:
                environment["PATH"] = str(Path(compiler).parent) + os.pathsep + environment.get("PATH", "")
        self.assertIsNotNone(compiler, "clang++ is required for the bounded ReadConst regression")
        with tempfile.TemporaryDirectory(prefix="order1886-readconst-") as directory:
            cpp = Path(directory) / "readconst.cpp"
            exe = Path(directory) / ("readconst.exe" if os.name == "nt" else "readconst")
            cpp.write_text(bounded_readconst_harness(SOURCE.read_text()), encoding="utf-8")
            command = [compiler, "-std=c++23", "-O2", "-UNDEBUG", "-Wall", "-Wextra", "-Werror",
                       "-I" + str(ROOT / "gpu/shim"), "-I" + str(ROOT / "gpu/shadps4"),
                       "-I" + str(ROOT / "gpu/third_party/magic_enum/include/magic_enum")]
            if os.name == "nt":
                command += ["-I" + str(toolchain / "include"), "-L" + str(toolchain / "lib")]
            subprocess.run(command + [str(cpp), "-lfmt", "-o", str(exe)],
                           check=True, env=environment)
            subprocess.run([str(exe)], check=True, env=environment)
            rejected = subprocess.run([str(exe), 'invalid-pointer'], env=environment,
                                      capture_output=True, text=True)
            self.assertEqual(rejected.returncode, 86, rejected.stdout + rejected.stderr)
            for expected in ('Invalid ReadConst pointer: shader=0x00000000804aeead stage=cpu',
                             'raw=deadbeef a5a50100', 'address=0xa5a50100deadbeef',
                             'requested_bytes=4194368', 'flat_size=8', 'load_mask=0x3',
                             'locations=[0, 1, 65535, 65535]', 'immediates=[0, 0, 0, 0]'):
                self.assertIn(expected, rejected.stderr)

    def test_failure_rolls_back_and_valid_roots_execute(self):
        compiler = shutil.which(os.environ.get("CXX", "clang++"))
        environment = os.environ.copy()
        if os.name == "nt":
            if compiler is None:
                candidate = (Path(environment.get("MSYS2_ROOT", r"C:\msys64")) /
                             "clang64/bin/clang++.exe")
                if candidate.is_file():
                    compiler = str(candidate)
            if compiler is not None:
                environment["PATH"] = (str(Path(compiler).parent) + os.pathsep +
                                       environment.get("PATH", ""))
        self.assertIsNotNone(compiler, "clang++ is required for the CPU SRT regression")
        with tempfile.TemporaryDirectory(prefix="order1886-srt-") as directory:
            cpp = Path(directory) / "srt_codegen.cpp"
            exe = Path(directory) / ("srt_codegen.exe" if os.name == "nt" else "srt_codegen")
            cpp.write_text(harness(SOURCE.read_text()), encoding="utf-8")
            subprocess.run([compiler, "-std=c++23", "-O2", "-UNDEBUG", "-Wall", "-Wextra",
                            "-Werror", "-I" + str(ROOT / "gpu/third_party/xbyak"),
                            str(cpp), "-o", str(exe)], check=True, env=environment)
            subprocess.run([str(exe)], check=True, env=environment)


if __name__ == "__main__":
    unittest.main()
