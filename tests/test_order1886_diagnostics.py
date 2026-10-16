import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from order1886_diagnostics import prepared_imports, reference_symbols, run_observations


class PreparedImportsTests(unittest.TestCase):
    def test_exact_table_index_survives_module_binding_and_segment_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "boot.bin"
            names = [b"first#libkernel", b"mqULNdimTn0#libScePosix"]
            path.write_bytes(struct.pack("<8s6Q", b"PS4BOOT5", 3, 0, 1, 1, 2, 0)
                             + bytes(40) + struct.pack("<Q", 1) + bytes(56)
                             + struct.pack("<Q", 1) + bytes(24) + bytes(24)
                             + b"".join(n.ljust(128, b"\0") for n in names)
                             + bytes(32) + b"abc")
            self.assertEqual(prepared_imports(path), [n.decode() for n in names])
            path.write_bytes(path.read_bytes()[:-1])
            with self.assertRaisesRegex(ValueError, "size does not match"):
                prepared_imports(path)

    def test_wrong_format_is_not_silently_interpreted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "boot.bin"
            for magic in (b"G3PROBE2", b"G3PROBE5"):
                with self.subTest(magic=magic):
                    path.write_bytes(struct.pack("<8s6Q", magic, *([0] * 6)))
                    with self.assertRaisesRegex(ValueError, "PS4BOOT5"):
                        prepared_imports(path)


class EvidenceTests(unittest.TestCase):
    def test_missing_list_does_not_mark_first_entry_as_reached(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "boot.log"
            log.write_text("MISSING: first#libkernel\nMISSING: mqULNdimTn0#libScePosix\n"
                           "STOP: first unsupported PS4 import: mqULNdimTn0#libScePosix (index 237)\n"
                           "Caller return offset: 0x2986c3; first argument: 0x1\n"
                           "Entering original x86-64 code guest offset 0xa0\n"
                           "Module 0 initializer returned 0\n"
                           "GPU: window and Vulkan presenter ready\n", encoding="utf-8")
            record = root / "boot.json"
            record.write_text(json.dumps({"log": str(log), "exit_code": 20}), encoding="utf-8")
            result = run_observations([record])[0]
            self.assertEqual(result["missing_imports"], ["first#libkernel", "mqULNdimTn0#libScePosix"])
            self.assertEqual(result["fatal_imports"], [{"canonical": "mqULNdimTn0#libScePosix", "index": 237}])
            self.assertEqual(result["caller_addresses"], ["0x2986c3"])
            self.assertTrue(result["original_entry_observed"])
            self.assertEqual(result["module_initializers"], ["Module 0 initializer returned 0"])
            self.assertNotIn("gameplay_verified", result)

    def test_reference_registration_keeps_library_module_and_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src/core/libraries/kernel").mkdir(parents=True)
            path = root / "src/core/libraries/kernel/spec.cpp"
            path.write_text('LIB_FUNCTION("nid", "libScePosix", 1, "libkernel", ORBIS(posix_key_create));\n', encoding="utf-8")
            registrations, names = reference_symbols(root, {"nid"})
            entry = registrations["nid#libScePosix"][0]
            self.assertEqual(entry["module"], "libkernel")
            self.assertEqual(entry["implementation"], "ORBIS(posix_key_create)")
            self.assertEqual(entry["line"], 1)
            self.assertIn("native support unverified", entry["status"])
            self.assertEqual(names, {})


if __name__ == "__main__":
    unittest.main()
