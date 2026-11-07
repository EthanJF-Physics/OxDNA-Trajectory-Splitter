"""Synthetic unit tests for strict validation. No research data is generated here."""
from pathlib import Path
import tempfile
import unittest

from oxdna_splitter.validation import ValidationError, validate_files, validate_topology


class StrictValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.top = self.root / "tiny.top"
        self.dat = self.root / "tiny.dat"
        self.top.write_text("2 1\n1 A -1 1\n1 T 0 -1\n", encoding="ascii")
        self.dat.write_text(
            "t = 10\nb = 10 10 10\nE = -1 0 1\n"
            "0 0 0 1 0 0 0 1 0\n"
            "1 0 0 1 0 0 0 1 0\n", encoding="ascii"
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_valid_minimal_dataset(self):
        summary = validate_files(self.top, self.dat)
        self.assertEqual(summary.topology.nucleotide_count, 2)
        self.assertEqual(summary.frame_count, 1)
        self.assertEqual(summary.nucleotide_fields, 9)

    def test_crlf_and_15_field_records(self):
        lines = ["t = 11", "b = 10 10 10", "E = -1 0 1",
                 " ".join(["1"] * 15), " ".join(["2"] * 15)]
        self.dat.write_bytes("\r\n".join(lines).encode("ascii"))
        summary = validate_files(self.top, self.dat)
        self.assertEqual(summary.nucleotide_fields, 15)
        self.assertIn("CRLF", summary.newline_styles)

    def test_nan_rejected(self):
        self.dat.write_text(
            "t = 10\nb = 10 10 10\nE = -1 0 1\n"
            "0 0 0 1 0 0 0 1 0\n1 0 0 1 0 0 0 1 nan\n", encoding="ascii"
        )
        with self.assertRaises(ValidationError) as caught:
            validate_files(self.top, self.dat)
        self.assertEqual(caught.exception.code, "INVALID_NUMERIC_FIELD")

    def test_incomplete_frame_rejected(self):
        self.dat.write_text("t = 10\nb = 10 10 10\nE = -1 0 1\n0 0 0 1 0 0 0 1 0\n")
        with self.assertRaises(ValidationError) as caught:
            validate_files(self.top, self.dat)
        self.assertEqual(caught.exception.code, "INCOMPLETE_FRAME")

    def test_topology_count_mismatch_rejected(self):
        self.top.write_text("3 1\n1 A -1 1\n1 T 0 -1\n", encoding="ascii")
        with self.assertRaises(ValidationError) as caught:
            validate_topology(self.top)
        self.assertEqual(caught.exception.code, "TOPOLOGY_COUNT_MISMATCH")

    def test_blank_line_rejected(self):
        self.dat.write_text(
            "t = 10\nb = 10 10 10\nE = -1 0 1\n\n"
            "0 0 0 1 0 0 0 1 0\n1 0 0 1 0 0 0 1 0\n"
        )
        with self.assertRaises(ValidationError) as caught:
            validate_files(self.top, self.dat)
        self.assertEqual(caught.exception.code, "BLANK_RECORD")

    def test_15_to_9_field_change_rejected(self):
        self.dat.write_text(
            "t = 10\nb = 10 10 10\nE = -1 0 1\n"
            + " ".join(["1"] * 15) + "\n"
            + " ".join(["1"] * 9) + "\n"
        )
        with self.assertRaises(ValidationError) as caught:
            validate_files(self.top, self.dat)
        self.assertEqual(caught.exception.code, "INCONSISTENT_RECORD_FORMAT")


    def test_mixed_line_endings_and_missing_final_newline(self):
        content = (
            b"t = 12\r\nb = 10 10 10\nE = -1 0 1\r\n"
            b"0 0 0 1 0 0 0 1 0\n1 0 0 1 0 0 0 1 0"
        )
        self.dat.write_bytes(content)
        summary = validate_files(self.top, self.dat)
        self.assertEqual(summary.frame_count, 1)
        self.assertIn("LF", summary.newline_styles)
        self.assertIn("CRLF", summary.newline_styles)
        self.assertIn("NONE", summary.newline_styles)

    def test_wrong_header_order_rejected(self):
        self.dat.write_text(
            "b = 10 10 10\nt = 10\nE = -1 0 1\n"
            "0 0 0 1 0 0 0 1 0\n1 0 0 1 0 0 0 1 0\n"
        )
        with self.assertRaises(ValidationError) as caught:
            validate_files(self.top, self.dat)
        self.assertEqual(caught.exception.code, "INVALID_FRAME_HEADER")

    def test_oversized_record_rejected(self):
        self.dat.write_bytes(
            b"t = 10\nb = 10 10 10\nE = -1 0 1\n"
            + b"1 " * 2050 + b"\n"
        )
        with self.assertRaises(ValidationError) as caught:
            validate_files(self.top, self.dat)
        self.assertEqual(caught.exception.code, "RECORD_TOO_LONG")


    def test_extra_topology_header_field_rejected(self):
        self.top.write_text("2 1 unexpected\n1 A -1 1\n1 T 0 -1\n", encoding="ascii")
        with self.assertRaises(ValidationError) as caught:
            validate_topology(self.top)
        self.assertEqual(caught.exception.code, "INVALID_TOPOLOGY_HEADER")


if __name__ == "__main__":
    unittest.main()
