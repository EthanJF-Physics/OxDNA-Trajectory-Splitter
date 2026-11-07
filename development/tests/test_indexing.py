"""Synthetic index tests. Fixtures are disposable and not research data."""
from pathlib import Path
import tempfile
import unittest

from oxdna_splitter.indexing import (
    IndexBuildError, IndexFormatError, IndexSourceMismatch, build_index, open_index,
)


class BinaryIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.top = self.root / "tiny.top"
        self.dat = self.root / "tiny.dat"
        self.idx = self.root / "tiny.dat.oxidx"
        self.top.write_text("2 1\n1 A -1 1\n1 T 0 -1\n", encoding="ascii")
        self.frame1 = ("t = 10\nb = 10 10 10\nE = -1 0 1\n"
                       "0 0 0 1 0 0 0 1 0\n1 0 0 1 0 0 0 1 0\n").encode("ascii")
        self.frame2 = ("t = 11\nb = 10 10 10\nE = -1 0 1\n"
                       "2 0 0 1 0 0 0 1 0\n3 0 0 1 0 0 0 1 0").encode("ascii")
        self.dat.write_bytes(self.frame1 + self.frame2)

    def tearDown(self):
        self.temp.cleanup()

    def test_build_offsets_and_exact_frame_ranges(self):
        result = build_index(self.top, self.dat, self.idx)
        self.assertFalse(result.reused)
        with open_index(self.idx, self.top, self.dat) as index:
            self.assertEqual(index.summary.frame_count, 2)
            self.assertEqual(index.offset(0), 0)
            self.assertEqual(index.frame_range(1), (0, len(self.frame1)))
            self.assertEqual(index.frame_range(2), (len(self.frame1), len(self.frame1 + self.frame2)))
            self.assertEqual(index.offset(2), self.dat.stat().st_size)

    def test_valid_index_is_reused(self):
        build_index(self.top, self.dat, self.idx)
        result = build_index(self.top, self.dat, self.idx)
        self.assertTrue(result.reused)

    def test_changed_source_is_rebuilt(self):
        build_index(self.top, self.dat, self.idx)
        self.dat.write_bytes(self.frame1 + self.frame2 + b"\n" + self.frame1)
        result = build_index(self.top, self.dat, self.idx)
        self.assertFalse(result.reused)
        self.assertEqual(result.frame_count, 3)

    def test_direct_open_rejects_changed_source(self):
        build_index(self.top, self.dat, self.idx)
        self.dat.write_bytes(self.frame1)
        with self.assertRaises(IndexSourceMismatch):
            open_index(self.idx, self.top, self.dat)

    def test_corrupt_index_is_rebuilt(self):
        build_index(self.top, self.dat, self.idx)
        raw = bytearray(self.idx.read_bytes())
        raw[-1] ^= 0x01
        self.idx.write_bytes(raw)
        result = build_index(self.top, self.dat, self.idx)
        self.assertFalse(result.reused)
        with open_index(self.idx, self.top, self.dat) as index:
            self.assertEqual(index.summary.frame_count, 2)

    def test_truncated_index_rejected(self):
        build_index(self.top, self.dat, self.idx)
        self.idx.write_bytes(b"OXIDX8")
        with self.assertRaises(IndexFormatError):
            open_index(self.idx, self.top, self.dat)

    def test_source_files_are_not_modified(self):
        before = (self.top.read_bytes(), self.dat.read_bytes())
        build_index(self.top, self.dat, self.idx)
        self.assertEqual((self.top.read_bytes(), self.dat.read_bytes()), before)

    def test_failed_rebuild_preserves_previous_index(self):
        build_index(self.top, self.dat, self.idx)
        previous_index = self.idx.read_bytes()
        self.dat.write_text("t = 10\nb = broken\n", encoding="ascii")
        with self.assertRaises(IndexBuildError):
            build_index(self.top, self.dat, self.idx, rebuild=True)
        self.assertEqual(self.idx.read_bytes(), previous_index)

    def test_index_may_not_overwrite_source(self):
        with self.assertRaises(IndexBuildError):
            build_index(self.top, self.dat, self.dat)


if __name__ == "__main__":
    unittest.main()
