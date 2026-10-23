"""Indexed indirect draws must not read more indices than the bound index buffer holds.

The Order builds indirect arguments on the GPU as count * 3 - 6; a record with count 0 gives
0xFFFFFFFA indices. GCN reads indices past INDEX_BUFFER_SIZE as 0, Vulkan has no bound: the
GPU spent minutes on one draw and presentation stopped (2026-10-22 gameplay freezes).
"""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_order1886_srt_codegen import function_body

ROOT = Path(__file__).resolve().parents[1]
SHADER = ROOT / "gpu/shadps4/video_core/host_shaders/indirect_index_clamp.comp"
RASTERIZER = ROOT / "gpu/shadps4/video_core/renderer_vulkan/vk_rasterizer.cpp"


def compiler_path():
    configured = os.environ.get("GLSLANG_COMPILER")
    if configured:
        return configured
    for name in ("glslang", "glslangValidator"):
        if found := shutil.which(name):
            return found
    candidate = Path(os.environ.get("MSYS2_ROOT", r"C:\msys64")) / "clang64/bin/glslang.exe"
    return str(candidate) if candidate.is_file() else None


def clamp(record, max_indices):
    """The shader's arithmetic, for the cases below."""
    count, instances, first, vertex_offset, first_instance = record
    available = max_indices - first if max_indices > first else 0
    return [min(count, available), instances, first, vertex_offset, first_instance]


class IndirectIndexClampTests(unittest.TestCase):
    def test_shader_compiles_and_clamps_against_first_index(self):
        compiler = compiler_path()
        self.assertIsNotNone(compiler, "glslang is required for the host shader regression")
        with tempfile.TemporaryDirectory(prefix="order1886-clamp-") as directory:
            output = Path(directory) / "clamp.spv"
            subprocess.run([compiler, "--target-env", "vulkan1.3", "-o", str(output), str(SHADER)],
                           check=True, capture_output=True)
        text = SHADER.read_text(encoding="utf-8")
        self.assertIn("push.max_indices > first_index ? push.max_indices - first_index : 0", text)
        self.assertIn("dst[d + 0] = min(src[s + 0], available);", text)
        for word in range(1, 5):
            self.assertRegex(text, rf"dst\[d \+ {word}\] = (src\[s \+ {word}\]|first_index);")

    def test_clamp_cases(self):
        # The freeze: count 0 records (0 * 3 - 6) with live instances.
        self.assertEqual(clamp([0xFFFFFFFA, 610, 0, 0, 0xFFFFFFFA], 4096)[0], 4096)
        self.assertEqual(clamp([0xFFFFFFFA, 17, 4000, 0, 6], 4096)[0], 96)
        # Valid draws are untouched; a first index past the buffer draws nothing.
        self.assertEqual(clamp([36, 4, 12, 7, 6], 4096), [36, 4, 12, 7, 6])
        self.assertEqual(clamp([36, 4, 5000, 0, 0], 4096)[0], 0)

    def test_indexed_indirect_draws_use_clamped_arguments(self):
        text = RASTERIZER.read_text(encoding="utf-8")
        record = function_body(text, "void Rasterizer::DrawIndirectRecord(")
        clamp_at = record.index("ClampIndexedIndirect(buffer, base, max_count, stride)")
        self.assertLess(record.index("BindIndexBuffer(0, true)"), clamp_at)
        self.assertLess(clamp_at, record.index("drawIndexedIndirect"))
        self.assertNotIn("const vk::Buffer args = buffer->Handle();", record)

        resolve = function_body(text, "void Rasterizer::ResolveIndexBuffer(")
        self.assertIn("regs.max_index_size != 0 ? request.indices : ~0u", resolve)

        clamp_fn = function_body(text, "std::pair<vk::Buffer, u64> Rasterizer::ClampIndexedIndirect(")
        self.assertIn("index_bind.count", clamp_fn)
        self.assertIn("vk::AccessFlagBits2::eIndirectCommandRead", clamp_fn)
        self.assertIn("Ps4Toggle::IndirectIndexClamp", clamp_fn)
        # Only the opt-outs (unknown bound, toggle) skip the clamp: a large batch grows the ring.
        self.assertEqual(clamp_fn.count("return {args->Handle(), offset};"), 1)
        self.assertIn("out_size > clamped_args_size", clamp_fn)


if __name__ == "__main__":
    unittest.main()
