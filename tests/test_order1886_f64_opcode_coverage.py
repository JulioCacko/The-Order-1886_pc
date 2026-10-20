"""Every double-precision opcode the IR declares must be declared and dispatched.

Two real defects came from exactly this gap: `uses_fp64` was set for only `PackDouble2x32` and
`UnpackDouble2x32` while the IR declares dozens of fp64 opcodes (so on a device that supports
float64 the module used `F64` without the capability — invalid SPIR-V), and `V_TRUNC_F64`/
`V_MIN_F64` were dispatched nowhere, so the translator's default arm logged and wrote nothing and
the destination register kept a stale value.

An opcode with no case is invisible to the C++ compiler, so this scan is the only thing that
notices. It reads the opcode table rather than a hand-written list, which means adding an fp64
opcode without wiring it up fails here.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
OPCODES = ROOT / 'gpu/shadps4/shader_recompiler/ir/opcodes.inc'
INFO = ROOT / 'gpu/shadps4/shader_recompiler/ir/passes/shader_info_collection_pass.cpp'
TRANSLATE = ROOT / 'gpu/shadps4/shader_recompiler/frontend/translate/vector_alu.cpp'


def declared_opcodes():
    text = OPCODES.read_text(encoding='utf-8')
    return set(re.findall(r'^\s*OPCODE\((\w+)\)', text, re.MULTILINE))


def uses_fp64_arm():
    text = INFO.read_text(encoding='utf-8')
    start = text.index('info.uses_fp64 = true;')
    # The arm is the run of case labels immediately before the assignment.
    before = text[:start]
    tail = before[before.rindex('break;') + len('break;'):] if 'break;' in before else before
    return set(re.findall(r'case IR::Opcode::(\w+):', tail))


def dispatched_opcodes():
    text = TRANSLATE.read_text(encoding='utf-8')
    return set(re.findall(r'case Opcode::(\w+):', text))


def fp64_opcodes():
    return {name for name in declared_opcodes()
            if name.endswith('64') and ('FP' in name or 'Convert' in name or 'Double' in name)}


class Fp64CoverageTests(unittest.TestCase):
    def test_every_fp64_opcode_marks_the_module_as_using_fp64(self):
        missing = sorted(fp64_opcodes() - uses_fp64_arm())
        self.assertFalse(missing, f'fp64 opcodes without uses_fp64: {missing}')

    def test_an_arm_that_only_covers_pack_and_unpack_is_detected(self):
        # Guard the guard: the original bug left exactly these two labels in place.
        arm = uses_fp64_arm()
        self.assertIn('FPAdd64', arm)
        self.assertGreater(len(arm), 10)

    def test_every_double_precision_vector_opcode_is_dispatched(self):
        declared = declared_opcodes()
        fp64_vector = {name for name in declared
                       if name.startswith('V_') and name.endswith('_F64')}
        # No exemptions: V_MAX_F64 is dispatched here exactly like its siblings, so excusing it
        # would hide the same defect the test exists to catch.
        missing = sorted(fp64_vector - dispatched_opcodes())
        self.assertFalse(missing, f'fp64 vector opcodes dispatched nowhere: {missing}')

    def test_the_dispatch_scan_sees_real_entries(self):
        dispatched = dispatched_opcodes()
        for name in ('V_MIN_F64', 'V_TRUNC_F64', 'V_MAX_F64', 'V_CVT_F64_F32'):
            self.assertIn(name, dispatched)


if __name__ == '__main__':
    unittest.main()
