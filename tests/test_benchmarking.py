"""Benchmark tests. All data here is SYNTHETIC and generated in temporary directories."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from oxdna_splitter import benchmarking
from oxdna_splitter.benchmarking import (
    BenchmarkError, format_report_text, generate_synthetic_dataset, run_benchmark, write_report,
)
from oxdna_splitter.cli import main as cli_main
from oxdna_splitter.validation import validate_files


class BenchmarkTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.work = self.root / "work"
        self.work.mkdir()
        self.top, self.dat = generate_synthetic_dataset(self.data, 50, 4)

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli_main(list(args))
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()


class SyntheticGeneratorTests(BenchmarkTestBase):
    def test_generated_dataset_passes_strict_validation(self):
        summary = validate_files(self.top, self.dat)
        self.assertEqual((summary.nucleotide_count, summary.frame_count, summary.nucleotide_fields), (50, 4, 9))

    def test_generation_is_deterministic(self):
        other = self.root / "other"
        other.mkdir()
        _, dat2 = generate_synthetic_dataset(other, 50, 4)
        self.assertEqual(self.dat.read_bytes(), dat2.read_bytes())

    def test_invalid_sizes_rejected(self):
        for nucleotides, frames in ((1, 1), (10, 0), (0, 5)):
            with self.assertRaises(BenchmarkError):
                generate_synthetic_dataset(self.data, nucleotides, frames)


class RunBenchmarkTests(BenchmarkTestBase):
    def bench(self, **kwargs):
        kwargs.setdefault("data_kind", "synthetic")
        kwargs.setdefault("repeats", 2)
        kwargs.setdefault("work_dir", self.work)
        return run_benchmark(self.top, self.dat, **kwargs)

    def test_report_contents_and_labelling(self):
        report = self.bench()
        self.assertEqual(report["data_kind"], "synthetic")
        self.assertIn("SYNTHETIC", report["data_notice"])
        self.assertEqual(report["sources"]["frames"], 4)
        self.assertEqual(report["repeats"], 2)
        for key in ("index_build", "index_reuse", "extraction"):
            self.assertEqual(len(report["results"][key]["seconds"]), 2)
            self.assertGreater(report["results"][key]["median_seconds"], 0)
            self.assertGreater(report["peak_python_memory_bytes"][key], 0)
        self.assertEqual(len(report["sources"]["trajectory"]["sha256"]), 64)
        self.assertEqual(len(report["extraction"]["output_sha256"]), 64)
        self.assertTrue(report["sources_unchanged_after_benchmark"])
        json.dumps(report)  # must be JSON-serializable

    def test_research_label_is_carried_through(self):
        report = self.bench(data_kind="research", repeats=1)
        self.assertIn("REAL RESEARCH DATA", report["data_notice"])
        self.assertIn("RESEARCH DATA", format_report_text(report))

    def test_data_kind_must_be_explicit_and_valid(self):
        for bad in (None, "", "real", "SYNTHETIC"):
            with self.assertRaises(BenchmarkError):
                self.bench(data_kind=bad)

    def test_invalid_repeats_and_work_dir_rejected(self):
        for bad in (0, 51, -1, 2.5):
            with self.assertRaises(BenchmarkError):
                self.bench(repeats=bad)
        with self.assertRaises(BenchmarkError):
            self.bench(work_dir=self.root / "missing")

    def test_default_and_explicit_frame_selection(self):
        self.assertEqual(self.bench()["extraction"]["frames_spec"], "1-2")
        report = self.bench(frames_spec="4,1")
        self.assertEqual(report["extraction"]["frames_selected"], 2)

    def test_inputs_unchanged_and_no_files_left_behind(self):
        before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in (self.top, self.dat)]
        listing = sorted(p.name for p in self.data.iterdir())
        self.bench()
        self.assertEqual([(p.read_bytes(), p.stat().st_mtime_ns) for p in (self.top, self.dat)], before)
        self.assertEqual(sorted(p.name for p in self.data.iterdir()), listing)  # no index beside the data
        self.assertEqual(list(self.work.iterdir()), [])  # scratch directory removed

    def test_existing_default_index_is_not_touched(self):
        from oxdna_splitter.indexing import build_index, default_index_path
        build_index(self.top, self.dat)
        idx = default_index_path(self.dat)
        before = (idx.read_bytes(), idx.stat().st_mtime_ns)
        self.bench()
        self.assertEqual((idx.read_bytes(), idx.stat().st_mtime_ns), before)

    def test_source_change_during_benchmark_is_detected(self):
        real = benchmarking._hash_file
        calls = {"n": 0}

        def flaky(path):
            calls["n"] += 1
            digest = real(path)
            return digest if calls["n"] <= 2 else "0" * 64

        with mock.patch.object(benchmarking, "_hash_file", flaky):
            with self.assertRaises(BenchmarkError):
                self.bench()
        self.assertEqual(list(self.work.iterdir()), [])

    def test_failure_still_cleans_scratch(self):
        with mock.patch.object(benchmarking, "extract_frames", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.bench()
        self.assertEqual(list(self.work.iterdir()), [])


class ReportFileTests(BenchmarkTestBase):
    def setUp(self):
        super().setUp()
        self.report = run_benchmark(self.top, self.dat, data_kind="synthetic", repeats=1, work_dir=self.work)
        self.protected = (("topology", self.top.resolve()), ("trajectory", self.dat.resolve()))
        self.path = self.root / "report.json"

    def test_report_round_trips_as_json(self):
        write_report(self.report, self.path, self.protected)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), self.report)

    def test_existing_report_refused_unless_overwrite(self):
        self.path.write_text("keep", encoding="utf-8")
        with self.assertRaises(BenchmarkError):
            write_report(self.report, self.path, self.protected)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "keep")
        write_report(self.report, self.path, self.protected, overwrite=True)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["schema"], 1)

    def test_report_may_not_replace_sources(self):
        before = self.dat.read_bytes()
        for target in (self.top, self.dat):
            with self.assertRaises(BenchmarkError):
                write_report(self.report, target, self.protected, overwrite=True)
        self.assertEqual(self.dat.read_bytes(), before)
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.endswith(".tmp")], [])


class BenchmarkCliTests(BenchmarkTestBase):
    def test_generate_synthetic_creates_missing_work_dir(self):
        work = self.root / "new" / "nested-work"
        report = self.root / "missing-work-report.json"
        code, out, err = self.run_cli(
            "benchmark", "--generate-synthetic", "60", "4", "--repeats", "1",
            "--work-dir", str(work), "--report", str(report),
        )
        self.assertEqual(code, 0, err)
        self.assertTrue(work.is_dir())
        self.assertEqual(list(work.iterdir()), [])
        self.assertTrue(report.is_file())

    def test_generate_synthetic_mode(self):
        report = self.root / "r.json"
        code, out, _ = self.run_cli("benchmark", "--generate-synthetic", "60", "4", "--repeats", "1",
                                    "--work-dir", str(self.work), "--report", str(report))
        self.assertEqual(code, 0)
        self.assertIn("SYNTHETIC DATA", out)
        self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["data_kind"], "synthetic")
        self.assertEqual(list(self.work.iterdir()), [])

    def test_real_files_require_explicit_data_kind(self):
        code, _, err = self.run_cli("benchmark", "-t", str(self.top), "-d", str(self.dat))
        self.assertEqual(code, 2)
        self.assertIn("--data-kind", err)

    def test_research_mode_is_labelled(self):
        code, out, _ = self.run_cli("benchmark", "-t", str(self.top), "-d", str(self.dat),
                                    "--data-kind", "research", "--repeats", "1", "--work-dir", str(self.work))
        self.assertEqual(code, 0)
        self.assertIn("RESEARCH DATA", out)
        self.assertNotIn("SYNTHETIC DATA", out)

    def test_conflicting_options_rejected(self):
        code, _, _ = self.run_cli("benchmark", "--generate-synthetic", "60", "4", "-t", str(self.top))
        self.assertEqual(code, 2)
        code, _, _ = self.run_cli("benchmark")
        self.assertEqual(code, 2)

    def test_existing_report_is_refused_before_any_benchmarking(self):
        report = self.root / "r.json"
        report.write_text("keep", encoding="utf-8")
        with mock.patch("oxdna_splitter.cli.run_benchmark", side_effect=AssertionError("ran too early")):
            code, _, err = self.run_cli("benchmark", "--generate-synthetic", "60", "4", "--report", str(report))
            self.assertEqual(code, 6)
            self.assertIn("already exists", err)
            code, _, _ = self.run_cli("benchmark", "-t", str(self.top), "-d", str(self.dat), "--data-kind", "research", "--report", str(self.dat), "--overwrite")
            self.assertEqual(code, 6)
        self.assertEqual(report.read_text(encoding="utf-8"), "keep")

    def test_bad_repeats_exit_code_6(self):
        code, _, err = self.run_cli("benchmark", "--generate-synthetic", "60", "4", "--repeats", "0")
        self.assertEqual(code, 6)
        self.assertIn("BENCHMARK FAILED", err)

    def test_invalid_input_files_reported_not_crashed(self):
        self.dat.write_text("t = 1\nb = broken\n", encoding="ascii")
        code, _, err = self.run_cli("benchmark", "-t", str(self.top), "-d", str(self.dat),
                                    "--data-kind", "research", "--repeats", "1", "--work-dir", str(self.work))
        self.assertIn(code, (4, 5, 6))
        self.assertIn("FAILED", err)
        self.assertEqual(list(self.work.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
