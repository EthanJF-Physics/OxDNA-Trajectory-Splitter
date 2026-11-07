"""Synthetic extraction tests. Fixtures are disposable and are not research data."""
import contextlib
import hashlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from oxdna_splitter import extraction
from oxdna_splitter.cli import main as cli_main
from oxdna_splitter.extraction import (
    ExtractionError, ExtractionVerificationError, FrameRangeError, OutputPathError,
    extract_frames, parse_frame_ranges, plan_extraction,
)
from oxdna_splitter.indexing import IndexSourceMismatch, build_index
from oxdna_splitter.validation import validate_files


def make_frame(t: int, newline: str = "\n", final_newline: bool = True) -> bytes:
    lines = [
        f"t = {t}", "b = 10 10 10", "E = -1 0 1",
        f"{t} 0 0 1 0 0 0 1 0", f"{t + 1} 0 0 1 0 0 0 1 0",
    ]
    return (newline.join(lines) + (newline if final_newline else "")).encode("ascii")


class ExtractionTestBase(unittest.TestCase):
    final_newline = False  # the last source frame lacks a final line terminator

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.top = self.root / "tiny.top"
        self.dat = self.root / "tiny.dat"
        self.idx = self.root / "tiny.dat.oxidx"
        self.out = self.root / "out.dat"
        self.top.write_text("2 1\n1 A -1 1\n1 T 0 -1\n", encoding="ascii")
        self.frames = [make_frame(100 + 10 * i) for i in range(4)]
        self.frames.append(make_frame(140, final_newline=self.final_newline))
        self.dat.write_bytes(b"".join(self.frames))
        build_index(self.top, self.dat, self.idx)

    def tearDown(self):
        self.temp.cleanup()

    def extract(self, spec, **kwargs):
        return extract_frames(self.top, self.dat, spec, self.out, index_path=self.idx, **kwargs)

    def leftovers(self):
        return sorted(p.name for p in self.root.iterdir() if p.name.endswith(".tmp"))


class FrameRangeParsingTests(unittest.TestCase):
    def test_valid_specs_preserve_requested_order(self):
        ranges = parse_frame_ranges("5-6, 1 ,3-4", 6)
        self.assertEqual([(r.start, r.end) for r in ranges], [(5, 6), (1, 1), (3, 4)])

    def test_invalid_specs_rejected(self):
        for spec in ["", "  ", "0", "a", "3-1", "1-", "-2", "1,,2", "1,", "1-2-3", "+1", "1.5", "\u00b2", "1 2"]:
            with self.subTest(spec=spec):
                with self.assertRaises(FrameRangeError):
                    parse_frame_ranges(spec, 10)

    def test_out_of_range_rejected(self):
        with self.assertRaises(FrameRangeError) as caught:
            parse_frame_ranges("1-6", 5)
        self.assertEqual(caught.exception.code, "FRAME_OUT_OF_RANGE")

    def test_overlaps_rejected_even_out_of_order_or_duplicated(self):
        for spec in ["1-5,3-7", "7,1-8", "3,3", "5-9,1-5"]:
            with self.subTest(spec=spec):
                with self.assertRaises(FrameRangeError) as caught:
                    parse_frame_ranges(spec, 10)
                self.assertEqual(caught.exception.code, "OVERLAPPING_FRAME_RANGES")

    def test_adjacent_ranges_are_not_overlapping(self):
        self.assertEqual(len(parse_frame_ranges("1-3,4-6", 6)), 2)


class ExactExtractionTests(ExtractionTestBase):
    def test_single_range_is_byte_identical(self):
        result = self.extract("2-3")
        self.assertEqual(self.out.read_bytes(), self.frames[1] + self.frames[2])
        self.assertEqual(result.frames_extracted, 2)
        self.assertEqual(result.bytes_written, len(self.frames[1] + self.frames[2]))
        self.assertEqual(result.sha256, hashlib.sha256(self.out.read_bytes()).hexdigest())
        self.assertEqual(result.separator_bytes_inserted, 0)
        self.assertFalse(result.overwritten)

    def test_multiple_ranges_keep_requested_order(self):
        self.extract("4-5,1-2")
        self.assertEqual(self.out.read_bytes(), self.frames[3] + self.frames[4] + b"\n" + self.frames[0] + self.frames[1])

    def test_multiple_ranges_without_separator_are_pure_concatenation(self):
        self.extract("3-4,1-2")
        self.assertEqual(self.out.read_bytes(), b"".join(self.frames[2:4] + self.frames[0:2]))

    def test_single_frames_and_mixed_specs(self):
        self.extract("3,1,5")
        self.assertEqual(self.out.read_bytes(), self.frames[2] + self.frames[0] + self.frames[4])

    def test_all_frames_reproduce_the_source_exactly(self):
        self.extract("1-5")
        self.assertEqual(self.out.read_bytes(), self.dat.read_bytes())

    def test_final_frame_without_newline_is_copied_exactly_when_last(self):
        self.extract("1,5")
        self.assertEqual(self.out.read_bytes(), self.frames[0] + self.frames[4])
        self.assertFalse(self.out.read_bytes().endswith(b"\n"))

    def test_final_frame_in_the_middle_gets_one_separator(self):
        result = self.extract("5,1")
        self.assertEqual(result.separator_bytes_inserted, 1)
        self.assertEqual(self.out.read_bytes(), self.frames[4] + b"\n" + self.frames[0])
        self.assertEqual(validate_files(self.top, self.out).frame_count, 2)

    def test_separator_matches_crlf_style(self):
        frames = [make_frame(10, "\r\n"), make_frame(20, "\r\n", final_newline=False)]
        self.dat.write_bytes(b"".join(frames))
        build_index(self.top, self.dat, self.idx, rebuild=True)
        result = self.extract("2,1")
        self.assertEqual(result.separator_bytes_inserted, 2)
        self.assertEqual(self.out.read_bytes(), frames[1] + b"\r\n" + frames[0])

    def test_no_separator_when_source_already_ends_with_newline(self):
        self.dat.write_bytes(b"".join(self.frames[:4]))
        build_index(self.top, self.dat, self.idx, rebuild=True)
        result = self.extract("4,1")
        self.assertEqual(result.separator_bytes_inserted, 0)
        self.assertEqual(self.out.read_bytes(), self.frames[3] + self.frames[0])

    def test_output_is_strictly_valid_and_matches_frame_count(self):
        self.extract("5,2-3")
        summary = validate_files(self.top, self.out)
        self.assertEqual(summary.frame_count, 3)

    def test_multi_chunk_copy_is_exact(self):
        with mock.patch.object(extraction, "COPY_CHUNK_BYTES", 7):
            self.extract("4-5,1-2")
        self.assertEqual(self.out.read_bytes(), self.frames[3] + self.frames[4] + b"\n" + self.frames[0] + self.frames[1])


class SourceSafetyTests(ExtractionTestBase):
    def snapshot(self):
        return [(p.read_bytes(), p.stat().st_mtime_ns) for p in (self.top, self.dat, self.idx)]

    def test_sources_and_index_unchanged_after_success(self):
        before = self.snapshot()
        self.extract("2-4,1")
        self.assertEqual(self.snapshot(), before)

    def test_sources_and_index_unchanged_after_failure(self):
        before = self.snapshot()
        with self.assertRaises(FrameRangeError):
            self.extract("1-9")
        self.assertEqual(self.snapshot(), before)

    def test_output_may_not_be_a_source_or_the_index(self):
        for target in (self.top, self.dat, self.idx):
            before = target.read_bytes()
            for overwrite in (False, True):
                with self.subTest(target=target.name, overwrite=overwrite):
                    with self.assertRaises(OutputPathError) as caught:
                        extract_frames(self.top, self.dat, "1", target, index_path=self.idx, overwrite=overwrite)
                    self.assertEqual(caught.exception.code, "OUTPUT_IS_PROTECTED_FILE")
                    self.assertEqual(target.read_bytes(), before)

    def test_alternate_spelling_of_source_path_is_still_refused(self):
        sneaky = self.root / "." / "sub" / ".." / "tiny.dat"
        (self.root / "sub").mkdir()
        with self.assertRaises(OutputPathError):
            extract_frames(self.top, self.dat, "1", sneaky, index_path=self.idx, overwrite=True)

    def test_hard_link_to_source_is_refused(self):
        link = self.root / "link.dat"
        try:
            os.link(self.dat, link)
        except (OSError, NotImplementedError):
            self.skipTest("hard links not supported here")
        before = self.dat.read_bytes()
        with self.assertRaises(OutputPathError):
            extract_frames(self.top, self.dat, "1", link, index_path=self.idx, overwrite=True)
        self.assertEqual(self.dat.read_bytes(), before)

    def test_directory_and_missing_parent_refused(self):
        with self.assertRaises(OutputPathError) as caught:
            extract_frames(self.top, self.dat, "1", self.root, index_path=self.idx)
        self.assertEqual(caught.exception.code, "OUTPUT_IS_DIRECTORY")
        with self.assertRaises(OutputPathError) as caught:
            extract_frames(self.top, self.dat, "1", self.root / "nope" / "o.dat", index_path=self.idx)
        self.assertEqual(caught.exception.code, "OUTPUT_DIRECTORY_MISSING")

    def test_stale_index_refused_and_nothing_written(self):
        self.dat.write_bytes(b"".join(self.frames[:3]))
        with self.assertRaises(IndexSourceMismatch):
            self.extract("1")
        self.assertFalse(self.out.exists())
        self.assertEqual(self.leftovers(), [])

    def test_missing_index_refused_unless_build_requested(self):
        self.idx.unlink()
        with self.assertRaises(ExtractionError) as caught:
            self.extract("1")
        self.assertEqual(caught.exception.code, "INDEX_NOT_FOUND")
        self.assertFalse(self.idx.exists())
        self.extract("1", build_index_if_needed=True)
        self.assertTrue(self.idx.exists())
        self.assertEqual(self.out.read_bytes(), self.frames[0])

    def test_build_index_refreshes_stale_index(self):
        self.dat.write_bytes(b"".join(self.frames[:3]))
        result = self.extract("3", build_index_if_needed=True)
        self.assertEqual(result.source_frame_count, 3)
        self.assertEqual(self.out.read_bytes(), self.frames[2])


class OutputProtectionTests(ExtractionTestBase):
    def test_existing_output_refused_and_left_intact(self):
        self.out.write_bytes(b"precious")
        with self.assertRaises(OutputPathError) as caught:
            self.extract("1")
        self.assertEqual(caught.exception.code, "OUTPUT_EXISTS")
        self.assertEqual(self.out.read_bytes(), b"precious")
        self.assertEqual(self.leftovers(), [])

    def test_overwrite_replaces_existing_output(self):
        self.out.write_bytes(b"old")
        result = self.extract("2", overwrite=True)
        self.assertTrue(result.overwritten)
        self.assertEqual(self.out.read_bytes(), self.frames[1])

    def test_output_appearing_during_extraction_is_not_clobbered(self):
        real_verify = extraction._verify_output

        def verify_then_create(*args, **kwargs):
            real_verify(*args, **kwargs)
            self.out.write_bytes(b"created meanwhile")

        with mock.patch.object(extraction, "_verify_output", verify_then_create):
            with self.assertRaises(OutputPathError):
                self.extract("1")
        self.assertEqual(self.out.read_bytes(), b"created meanwhile")
        self.assertEqual(self.leftovers(), [])

    def test_insufficient_disk_space_refused_before_writing(self):
        usage = mock.Mock(free=1)
        with mock.patch.object(extraction.shutil, "disk_usage", return_value=usage):
            with self.assertRaises(ExtractionError) as caught:
                self.extract("1-5")
        self.assertEqual(caught.exception.code, "INSUFFICIENT_DISK_SPACE")
        self.assertFalse(self.out.exists())
        self.assertEqual(self.leftovers(), [])


class VerificationAndCleanupTests(ExtractionTestBase):
    def test_corrupted_write_is_detected_and_not_published(self):
        original = extraction._write_all

        def corrupting(handle, data):
            original(handle, b"X" + bytes(data)[1:])

        with mock.patch.object(extraction, "_write_all", corrupting):
            with self.assertRaises(ExtractionVerificationError) as caught:
                self.extract("1-2")
        self.assertEqual(caught.exception.code, "OUTPUT_SHA256_MISMATCH")
        self.assertFalse(self.out.exists())
        self.assertEqual(self.leftovers(), [])

    def test_failed_overwrite_keeps_previous_output(self):
        self.out.write_bytes(b"previous good output")
        with mock.patch.object(extraction, "_verify_output", side_effect=ExtractionVerificationError("OUTPUT_INVALID", "x")):
            with self.assertRaises(ExtractionVerificationError):
                self.extract("1", overwrite=True)
        self.assertEqual(self.out.read_bytes(), b"previous good output")
        self.assertEqual(self.leftovers(), [])

    def test_keyboard_interrupt_cleans_up_and_publishes_nothing(self):
        with mock.patch.object(extraction, "_verify_output", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.extract("1-3")
        self.assertFalse(self.out.exists())
        self.assertEqual(self.leftovers(), [])

    def test_interrupt_in_the_middle_of_copying(self):
        calls = {"n": 0}
        original = extraction._copy_range

        def interrupt_second(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise KeyboardInterrupt
            return original(*args, **kwargs)

        with mock.patch.object(extraction, "_copy_range", interrupt_second):
            with self.assertRaises(KeyboardInterrupt):
                self.extract("1,3")
        self.assertFalse(self.out.exists())
        self.assertEqual(self.leftovers(), [])

    def test_only_own_temp_file_is_removed(self):
        foreign = self.root / ".out.dat.foreign.tmp"
        foreign.write_bytes(b"someone else's temp")
        with mock.patch.object(extraction, "_verify_output", side_effect=ExtractionVerificationError("OUTPUT_INVALID", "x")):
            with self.assertRaises(ExtractionVerificationError):
                self.extract("1")
        self.assertTrue(foreign.exists())
        self.assertEqual(self.leftovers(), [foreign.name])

    def test_source_change_during_extraction_blocks_publication(self):
        real_verify = extraction._verify_output

        def verify_then_touch(*args, **kwargs):
            real_verify(*args, **kwargs)
            os.utime(self.dat, ns=(1, 1))

        with mock.patch.object(extraction, "_verify_output", verify_then_touch):
            with self.assertRaises(ExtractionError) as caught:
                self.extract("1")
        self.assertEqual(caught.exception.code, "SOURCE_CHANGED")
        self.assertFalse(self.out.exists())
        self.assertEqual(self.leftovers(), [])


class DryRunAndCliTests(ExtractionTestBase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli_main(list(args))
        return code, out.getvalue(), err.getvalue()

    def base_args(self, frames, *extra):
        return ["extract", "-t", str(self.top), "-d", str(self.dat), "--index", str(self.idx),
                "-f", frames, "-o", str(self.out), *extra]

    def test_plan_writes_nothing(self):
        before = sorted(p.name for p in self.root.iterdir())
        plan = plan_extraction(self.top, self.dat, "5,1", self.out, index_path=self.idx)
        self.assertEqual(plan.frames_selected, 2)
        self.assertEqual(plan.expected_bytes, len(self.frames[4]) + 1 + len(self.frames[0]))
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), before)

    def test_plan_never_builds_a_missing_index(self):
        self.idx.unlink()
        with self.assertRaises(ExtractionError):
            plan_extraction(self.top, self.dat, "1", self.out, index_path=self.idx)
        self.assertFalse(self.idx.exists())

    def test_cli_extract_success(self):
        code, stdout, _ = self.run_cli(*self.base_args("2-3"))
        self.assertEqual(code, 0)
        self.assertIn("EXTRACTION COMPLETE", stdout)
        self.assertIn(hashlib.sha256(self.out.read_bytes()).hexdigest(), stdout)
        self.assertEqual(self.out.read_bytes(), self.frames[1] + self.frames[2])

    def test_cli_dry_run_writes_nothing(self):
        code, stdout, _ = self.run_cli(*self.base_args("2-3", "--dry-run"))
        self.assertEqual(code, 0)
        self.assertIn("DRY RUN OK", stdout)
        self.assertFalse(self.out.exists())
        self.assertEqual(self.leftovers(), [])

    def test_cli_refuses_existing_output_with_exit_code_5(self):
        self.out.write_bytes(b"keep me")
        code, _, stderr = self.run_cli(*self.base_args("1"))
        self.assertEqual(code, 5)
        self.assertIn("OUTPUT_EXISTS", stderr)
        self.assertEqual(self.out.read_bytes(), b"keep me")

    def test_cli_overwrite_flag(self):
        self.out.write_bytes(b"old")
        code, stdout, _ = self.run_cli(*self.base_args("1", "--overwrite"))
        self.assertEqual(code, 0)
        self.assertIn("Replaced existing:     yes", stdout)

    def test_cli_invalid_range_exit_code(self):
        code, _, stderr = self.run_cli(*self.base_args("3-1"))
        self.assertEqual(code, 5)
        self.assertIn("INVALID_FRAME_RANGE", stderr)
        self.assertFalse(self.out.exists())

    def test_cli_stale_index_exit_code_4(self):
        self.dat.write_bytes(b"".join(self.frames[:2]))
        code, _, stderr = self.run_cli(*self.base_args("1"))
        self.assertEqual(code, 4)
        self.assertIn("INDEX_PROBLEM", stderr)
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
