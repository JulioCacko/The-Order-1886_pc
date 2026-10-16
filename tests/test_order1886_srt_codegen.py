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


class SrtCodegenTests(unittest.TestCase):
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
