"""Build and run the production sampled-image guard with real IR, without Vulkan."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UniformGuardTests(unittest.TestCase):
    def test_cfg_shared_uses_and_snapshot_contract(self):
        environment = os.environ.copy()
        compiler = shutil.which(environment.get("CXX", "clang++"))
        if os.name == "nt" and compiler is None:
            candidate = Path(environment.get("MSYS2_ROOT", r"C:\msys64")) / "clang64/bin/clang++.exe"
            if candidate.is_file():
                compiler = str(candidate)
        self.assertIsNotNone(compiler, "clang++ is required for the uniform guard regression")
        environment["PATH"] = str(Path(compiler).parent) + os.pathsep + environment.get("PATH", "")
        ir = ROOT / "gpu/shadps4/shader_recompiler/ir"
        sources = [ROOT / "tests/test_sampled_image_uniform_guard.cpp",
                   ir / "passes/sampled_image_uniform_guard_pass.cpp"]
        sources += [ir / (name + ".cpp") for name in
                    ("basic_block", "microinstruction", "value", "opcodes", "type", "attribute", "patch")]
        with tempfile.TemporaryDirectory(prefix="order1886-uniform-guard-") as directory:
            exe = Path(directory) / ("guard.exe" if os.name == "nt" else "guard")
            command = [compiler, "-std=c++23", "-O1", "-UNDEBUG", "-DNOMINMAX",
                       "-DWIN32_LEAN_AND_MEAN", "-I" + str(ROOT / "gpu/shim"),
                       "-I" + str(ROOT / "gpu/shadps4"),
                       "-I" + str(ROOT / "gpu/third_party/gcn/include"),
                       "-I" + str(ROOT / "gpu/third_party/magic_enum/include"),
                       "-I" + str(ROOT / "gpu/third_party/magic_enum/include/magic_enum"),
                       *map(str, sources), "-lfmt", "-o", str(exe)]
            subprocess.run(command, check=True, env=environment)
            subprocess.run([str(exe)], check=True, env=environment, timeout=10)
            for mode in ("active-required-source", "missing-count"):
                result = subprocess.run([str(exe), mode], env=environment, timeout=10)
                self.assertEqual(result.returncode, 86, mode)


if __name__ == "__main__":
    unittest.main()
