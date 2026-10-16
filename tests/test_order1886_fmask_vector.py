"""Compile the exact FMask producer body against its required four-component contract."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.test_order1886_srt_codegen import function_body


ROOT = Path(__file__).resolve().parents[1]


class FmaskVectorTests(unittest.TestCase):
    def test_producer_is_vec4_and_applies_descriptor_selectors(self):
        source = (ROOT / "gpu/shadps4/shader_recompiler/ir/passes/resource_patching_pass.cpp").read_text()
        source = source[source.index("// Patch image instruction if image is FMask."):]
        block = function_body(source, "case IR::Opcode::ImageSampleRaw:")
        block = block[block.index("{") + 1:-1]
        harness = r'''
#include <array>
#include <cassert>
#include <stdexcept>
#include "shader_recompiler/ir/passes/fmask_identity.h"
namespace IR { using F32 = u32; }
struct Emitter {
    u32 Imm32(u32 bits) { return bits; }
    template <typename T> T BitCast(u32 bits) { return bits; }
    template <typename... T> auto CompositeConstruct(T... parts) {
        return std::array<u32, sizeof...(parts)>{parts...};
    }
};
struct Image { AmdGpu::CompMapping mapping; auto DstSelect() const { return mapping; } };
struct Inst {
    std::array<u32,4>& output;
    void ReplaceUsesWith(const std::array<u32,4>& value) { output = value; }
};
#undef ASSERT_MSG
#define ASSERT_MSG(condition, ...) if (!(condition)) throw std::runtime_error("unsupported FMask selector")
void Emit(std::array<u32,4>& output, AmdGpu::CompMapping selectors) {
    using Shader::Optimization::FmaskIdentityTexel;
    Image image{selectors};
    Emitter ir;
    Inst inst{output};
''' + block + r'''
}
int main() {
    using C = AmdGpu::CompSwizzle;
    std::array<u32,4> output{};
    Emit(output, {.array = std::array{C::Red,C::Red,C::Red,C::Red}});
    assert((output == std::array<u32,4>{0x76543210,0x76543210,0x76543210,0x76543210}));
    Emit(output, {.array = std::array{C::Green,C::Red,C::Zero,C::One}});
    assert((output == std::array<u32,4>{0xfedcba98,0x76543210,0,1}));
    bool rejected = false;
    try { Emit(output, {.array = std::array{C::Red,C::Red,C::Blue,C::Red}}); }
    catch (const std::runtime_error&) { rejected = true; }
    assert(rejected);
}
'''
        environment = os.environ.copy()
        compiler = shutil.which(environment.get("CXX", "clang++"))
        if os.name == "nt" and compiler is None:
            candidate = Path(environment.get("MSYS2_ROOT", r"C:\msys64")) / "clang64/bin/clang++.exe"
            if candidate.is_file():
                compiler = str(candidate)
        self.assertIsNotNone(compiler, "clang++ is required for the FMask CPU regression")
        environment["PATH"] = str(Path(compiler).parent) + os.pathsep + environment.get("PATH", "")
        with tempfile.TemporaryDirectory(prefix="order1886-fmask-") as directory:
            cpp = Path(directory) / "fmask.cpp"
            exe = Path(directory) / ("fmask.exe" if os.name == "nt" else "fmask")
            cpp.write_text(harness, encoding="utf-8")
            subprocess.run([compiler, "-std=c++23", "-O2", "-UNDEBUG", "-Wall", "-Wextra",
                            "-Werror", "-I" + str(ROOT / "gpu/shim"),
                            "-I" + str(ROOT / "gpu/shadps4"), str(cpp), "-o", str(exe)],
                           check=True, env=environment)
            subprocess.run([str(exe)], check=True, env=environment)


if __name__ == "__main__":
    unittest.main()
