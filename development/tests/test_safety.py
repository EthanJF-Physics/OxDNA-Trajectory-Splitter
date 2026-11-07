"""Phase 5 safety tests. Every fixture is SYNTHETIC, created in a temporary directory."""
import contextlib
import hashlib
import io
import os
from pathlib import Path
import stat
import tempfile
import tracemalloc
import unittest
from unittest import mock

from oxdna_splitter import indexing
from oxdna_splitter.benchmarking import generate_synthetic_dataset
from oxdna_splitter.cli import main as cli_main
from oxdna_splitter.extraction import ExtractionError, extract_frames
from oxdna_splitter.indexing import (
    IndexBuildError, IndexErrorBase, IndexSourceMismatch, build_index, open_index,
)


def frame(t, nl="\n", fields=9, records=2, final_newline=True):
    lines = [f"t = {t}", "b = 10 10 10", "E = -1 0 1"]
    lines += [" ".join([str(t + r)] * fields) for r in range(records)]
    return (nl.join(lines) + (nl if final_newline else "")).encode("ascii")


class Base(unittest.TestCase):
    records = 2

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.top = self.root / "t.top"
        self.dat = self.root / "t.dat"
        self.idx = self.root / "t.dat.oxidx"
        self.out = self.root / "out.dat"
        self.write_top(self.records)
        self.frames = [frame(100 + 10 * i, records=self.records) for i in range(5)]
        self.dat.write_bytes(b"".join(self.frames))

    def write_top(self, n):
        lines = [f"{n} 1"] + [f"1 A {i - 1 if i else -1} {i + 1 if i + 1 < n else -1}" for i in range(n)]
        self.top.write_text("\n".join(lines) + "\n", encoding="ascii")

    def tearDown(self):
        self.temp.cleanup()

    def tmp_files(self):
        return sorted(p.name for p in self.root.iterdir() if p.name.endswith(".tmp"))

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli_main(list(args))
        return code, out.getvalue(), err.getvalue()


class CorruptIndexTests(Base):
    def setUp(self):
        super().setUp()
        build_index(self.top, self.dat, self.idx)
        self.pristine = self.idx.read_bytes()

    def test_every_single_byte_flip_is_detected(self):
        for position in range(len(self.pristine)):
            damaged = bytearray(self.pristine)
            damaged[position] ^= 0x01
            self.idx.write_bytes(damaged)
            with self.subTest(position=position):
                with self.assertRaises(IndexErrorBase):
                    open_index(self.idx, self.top, self.dat).close()

    def test_every_truncation_is_detected(self):
        for length in range(len(self.pristine)):
            self.idx.write_bytes(self.pristine[:length])
            with self.subTest(length=length):
                with self.assertRaises(IndexErrorBase):
                    open_index(self.idx, self.top, self.dat).close()

    def test_appended_garbage_is_detected(self):
        self.idx.write_bytes(self.pristine + b"\0")
        with self.assertRaises(IndexErrorBase):
            open_index(self.idx, self.top, self.dat).close()

    def test_empty_index_file_is_rebuilt_by_index_command(self):
        self.idx.write_bytes(b"")
        result = build_index(self.top, self.dat, self.idx)
        self.assertFalse(result.reused)
        open_index(self.idx, self.top, self.dat).close()

    def test_extraction_refuses_every_damaged_index_and_writes_nothing(self):
        for position in (0, 9, 40, len(self.pristine) // 2, len(self.pristine) - 1):
            damaged = bytearray(self.pristine)
            damaged[position] ^= 0xFF
            self.idx.write_bytes(damaged)
            with self.subTest(position=position):
                with self.assertRaises(IndexErrorBase):
                    extract_frames(self.top, self.dat, "1-2", self.out, index_path=self.idx)
                self.assertFalse(self.out.exists())
                self.assertEqual(self.tmp_files(), [])

    def test_changed_topology_makes_index_stale(self):
        self.top.write_text(self.top.read_text(encoding="ascii") + "", encoding="ascii")  # same bytes
        open_index(self.idx, self.top, self.dat).close()
        self.write_top(self.records)
        self.top.write_bytes(self.top.read_bytes().replace(b"1 A", b"1 T", 1))
        with self.assertRaises(IndexSourceMismatch):
            open_index(self.idx, self.top, self.dat).close()

    def test_same_size_content_change_is_detected_by_hash(self):
        data = bytearray(self.dat.read_bytes())
        data[data.index(b"110")] = ord("9")  # same length, different bytes
        self.dat.write_bytes(data)
        with self.assertRaises(IndexSourceMismatch):
            open_index(self.idx, self.top, self.dat).close()

    def test_moved_files_need_a_new_index(self):
        moved = self.root / "moved"
        moved.mkdir()
        top2, dat2, idx2 = moved / "t.top", moved / "t.dat", moved / "t.dat.oxidx"
        top2.write_bytes(self.top.read_bytes())
        dat2.write_bytes(self.dat.read_bytes())
        idx2.write_bytes(self.pristine)
        with self.assertRaises(IndexSourceMismatch):
            open_index(idx2, top2, dat2).close()
        self.assertFalse(build_index(top2, dat2, idx2).reused)


class InterruptedIndexBuildTests(Base):
    def test_interrupt_during_scan_publishes_nothing(self):
        with mock.patch.object(indexing, "_scan_trajectory", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                build_index(self.top, self.dat, self.idx)
        self.assertFalse(self.idx.exists())
        self.assertEqual(self.tmp_files(), [])

    def test_interrupt_while_verifying_candidate_cleans_temp_and_keeps_old_index(self):
        build_index(self.top, self.dat, self.idx)
        before = self.idx.read_bytes()
        with mock.patch.object(indexing, "_read_index_file", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                build_index(self.top, self.dat, self.idx, rebuild=True)
        self.assertEqual(self.idx.read_bytes(), before)
        self.assertEqual(self.tmp_files(), [])

    def test_publication_failure_keeps_old_index_and_cleans_temp(self):
        build_index(self.top, self.dat, self.idx)
        before = self.idx.read_bytes()
        with mock.patch("os.replace", side_effect=PermissionError("locked")):
            with self.assertRaises(IndexBuildError):
                build_index(self.top, self.dat, self.idx, rebuild=True)
        self.assertEqual(self.idx.read_bytes(), before)
        self.assertEqual(self.tmp_files(), [])

    def test_source_modified_during_indexing_publishes_nothing(self):
        real = indexing._scan_trajectory

        def scan_then_modify(*args, **kwargs):
            result = real(*args, **kwargs)
            self.dat.write_bytes(self.dat.read_bytes() + b"")
            os.utime(self.dat, ns=(5, 5))
            return result

        with mock.patch.object(indexing, "_scan_trajectory", scan_then_modify):
            with self.assertRaises(IndexBuildError):
                build_index(self.top, self.dat, self.idx)
        self.assertFalse(self.idx.exists())
        self.assertEqual(self.tmp_files(), [])


class InvalidInputTests(Base):
    def test_invalid_trajectory_cannot_be_indexed_or_extracted(self):
        self.dat.write_bytes(self.dat.read_bytes() + b"garbage\n")
        with self.assertRaises(IndexBuildError):
            build_index(self.top, self.dat, self.idx)
        with self.assertRaises(IndexBuildError):
            extract_frames(self.top, self.dat, "1", self.out, index_path=self.idx, build_index_if_needed=True)
        self.assertFalse(self.out.exists())
        self.assertFalse(self.idx.exists())
        self.assertEqual(self.tmp_files(), [])

    def test_empty_inputs_rejected(self):
        for target in (self.top, self.dat):
            original = target.read_bytes()
            target.write_bytes(b"")
            with self.subTest(target=target.name):
                with self.assertRaises(IndexBuildError):
                    build_index(self.top, self.dat, self.idx)
            target.write_bytes(original)

    def test_missing_source_after_indexing_is_refused(self):
        build_index(self.top, self.dat, self.idx)
        self.dat.unlink()
        with self.assertRaises(IndexErrorBase):
            extract_frames(self.top, self.dat, "1", self.out, index_path=self.idx)
        self.assertFalse(self.out.exists())

    def test_topology_with_wrong_nucleotide_count_rejected(self):
        self.write_top(3)  # trajectory frames hold 2 records
        with self.assertRaises(IndexBuildError):
            build_index(self.top, self.dat, self.idx)

    def test_cli_exit_codes_for_bad_inputs(self):
        self.dat.write_bytes(b"not a trajectory\n")
        code, _, err = self.cli("validate", "-t", str(self.top), "-d", str(self.dat))
        self.assertEqual(code, 3)
        self.assertIn("VALIDATION FAILED", err)
        code, _, err = self.cli("index", "-t", str(self.top), "-d", str(self.dat))
        self.assertEqual(code, 4)
        code, _, err = self.cli("validate", "-t", str(self.root / "none.top"), "-d", str(self.dat))
        self.assertEqual(code, 3)


class FormatVariantTests(Base):
    def run_variant(self, nl, fields, records):
        self.records = records
        self.write_top(records)
        frames = [frame(10 * i, nl=nl, fields=fields, records=records) for i in range(1, 5)]
        self.dat.write_bytes(b"".join(frames))
        build_index(self.top, self.dat, self.idx)
        for spec, order in (("1-4", [0, 1, 2, 3]), ("4,3,2,1", [3, 2, 1, 0]), ("2-3,1", [1, 2, 0])):
            with self.subTest(nl=repr(nl), fields=fields, spec=spec):
                extract_frames(self.top, self.dat, spec, self.out, index_path=self.idx, overwrite=True)
                self.assertEqual(self.out.read_bytes(), b"".join(frames[i] for i in order))

    def test_crlf(self):
        self.run_variant("\r\n", 9, 2)

    def test_fifteen_fields(self):
        self.run_variant("\n", 15, 3)

    def test_crlf_fifteen_fields(self):
        self.run_variant("\r\n", 15, 2)

    def test_single_nucleotide_system(self):
        self.run_variant("\n", 9, 1)


class ManyFramesTests(Base):
    def test_thousands_of_frames_exact_and_ordered(self):
        frames = [frame(i, records=2) for i in range(3000)]
        self.dat.write_bytes(b"".join(frames))
        result = build_index(self.top, self.dat, self.idx)
        self.assertEqual(result.frame_count, 3000)
        extract_frames(self.top, self.dat, "2500-3000,1-10,1500", self.out, index_path=self.idx)
        expected = b"".join(frames[2499:3000] + frames[0:10] + [frames[1499]])
        self.assertEqual(self.out.read_bytes(), expected)
        extract_frames(self.top, self.dat, "1-3000", self.out, index_path=self.idx, overwrite=True)
        self.assertEqual(self.out.read_bytes(), self.dat.read_bytes())

    def test_range_just_past_the_end_is_refused(self):
        build_index(self.top, self.dat, self.idx)
        with self.assertRaises(ExtractionError):
            extract_frames(self.top, self.dat, "1-6", self.out, index_path=self.idx)
        self.assertFalse(self.out.exists())


class ImmutabilityTests(Base):
    def test_read_only_sources_work_and_stay_identical(self):
        paths = (self.top, self.dat)
        digests = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        for path in paths:
            os.chmod(path, stat.S_IREAD)
        try:
            mtimes = {p: p.stat().st_mtime_ns for p in paths}
            self.assertEqual(self.cli("validate", "-t", str(self.top), "-d", str(self.dat))[0], 0)
            self.assertEqual(self.cli("index", "-t", str(self.top), "-d", str(self.dat))[0], 0)
            self.assertEqual(self.cli("extract", "-t", str(self.top), "-d", str(self.dat), "-f", "2-4,1", "-o", str(self.out))[0], 0)
            self.assertEqual(self.cli("benchmark", "-t", str(self.top), "-d", str(self.dat), "--data-kind", "synthetic", "--repeats", "1", "--work-dir", str(self.root))[0], 0)
            for path in paths:
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digests[path])
                self.assertEqual(path.stat().st_mtime_ns, mtimes[path])
        finally:
            for path in paths:
                os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        self.assertEqual(self.tmp_files(), [])


class BoundedMemoryTests(unittest.TestCase):
    """Peak Python memory must not grow with file size (tracemalloc; see docs)."""

    @staticmethod
    def peak_for(directory: Path, nucleotides: int, frames: int) -> tuple[int, int]:
        directory.mkdir()
        top, dat = generate_synthetic_dataset(directory, nucleotides, frames)
        out = directory / "out.dat"
        tracemalloc.start()
        try:
            build_index(top, dat)
            extract_frames(top, dat, f"1-{frames}", out)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert out.read_bytes() == dat.read_bytes()
        return peak, dat.stat().st_size

    def test_peak_memory_does_not_scale_with_file_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            small_peak, small_size = self.peak_for(Path(tmp) / "small", 100, 6)
            large_peak, large_size = self.peak_for(Path(tmp) / "large", 100, 200)
        self.assertGreater(large_size, 30 * small_size)
        self.assertLess(large_peak - small_peak, 1536 * 1024)
        self.assertLess(large_peak, 4 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
