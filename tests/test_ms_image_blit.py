"""Check host MSAA blit SPIR-V types and lossless unsigned fetch/store on the CPU."""

import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "gpu/shadps4/video_core/host_shaders/ms_image_blit.frag"


def compiler_path():
    configured = os.environ.get("GLSLANG_COMPILER")
    if configured:
        return configured
    for name in ("glslang", "glslangValidator"):
        if found := shutil.which(name):
            return found
    candidate = Path(os.environ.get("MSYS2_ROOT", r"C:\msys64")) / "clang64/bin/glslang.exe"
    return str(candidate) if candidate.is_file() else None


def instructions(blob):
    words = struct.unpack("<" + "I" * (len(blob) // 4), blob)
    assert words[0] == 0x07230203
    offset = 5
    while offset < len(words):
        count, opcode = words[offset] >> 16, words[offset] & 0xffff
        assert count and offset + count <= len(words)
        yield opcode, words[offset + 1:offset + count]
        offset += count


class MsImageBlitTests(unittest.TestCase):
    def compile_shader(self, uint, msaa):
        compiler = compiler_path()
        self.assertIsNotNone(compiler, "glslang is required for the host blit regression")
        with tempfile.TemporaryDirectory(prefix="order1886-ms-blit-") as directory:
            output = Path(directory) / "blit.spv"
            defines = (["-DSRC_UINT=1"] if uint else []) + (["-DSRC_MSAA=1"] if msaa else [])
            subprocess.run([compiler, "--target-env", "vulkan1.3", *defines,
                            "-o", str(output), str(SOURCE)], check=True, capture_output=True)
            validator = Path(compiler).with_name("spirv-val.exe" if os.name == "nt" else "spirv-val")
            if validator.is_file():
                subprocess.run([str(validator), "--target-env", "vulkan1.3", str(output)],
                               check=True, capture_output=True)
            return list(instructions(output.read_bytes()))

    def check_contract(self, uint, msaa):
        code = self.compile_shader(uint, msaa)
        # SPIR-V 1.x: OpTypeInt/Float/Vector/Image/Pointer, OpVariable, OpImageFetch, OpStore.
        types = {args[0]: (opcode, args[1:]) for opcode, args in code
                 if opcode in (21, 22, 23, 25, 32)}
        images = [args for opcode, args in code if opcode == 25]
        self.assertEqual(len(images), 1)
        image = images[0]
        scalar_type = image[1]
        self.assertEqual(types[scalar_type], (21, (32, 0)) if uint else (22, (32,)))
        self.assertEqual(image[5], int(msaa))
        outputs = [args for opcode, args in code if opcode == 59 and args[2] == 3]
        self.assertEqual(len(outputs), 1)
        pointer_type, output_id, _ = outputs[0]
        _, (_, vector_type) = types[pointer_type]
        self.assertEqual(types[vector_type], (23, (scalar_type, 4)))
        fetches = [args for opcode, args in code if opcode == 95]
        self.assertEqual(len(fetches), 1)
        fetch_type, fetch_id, *_ = fetches[0]
        self.assertEqual(fetch_type, vector_type)
        stores = [args for opcode, args in code if opcode == 62 and args[0] == output_id]
        # The actual fetched uint vector is stored directly: no float conversion, bitcast,
        # normalization, clamp or arithmetic can change any of its 16-bit scalar values.
        self.assertEqual(stores, [(output_id, fetch_id)])

    def test_float_msaa_and_non_msaa_contract(self):
        for msaa in (False, True):
            with self.subTest(msaa=msaa):
                self.check_contract(uint=False, msaa=msaa)

    def test_uint_msaa_and_non_msaa_preserve_scalar_bits(self):
        for msaa in (False, True):
            with self.subTest(msaa=msaa):
                self.check_contract(uint=True, msaa=msaa)


if __name__ == "__main__":
    unittest.main()
