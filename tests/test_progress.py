"""Progress/timing infrastructure regression tests for v8.1."""
from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from oxdna_splitter.benchmarking import generate_synthetic_dataset
from oxdna_splitter.extraction import extract_frames
from oxdna_splitter.indexing import build_index
from oxdna_splitter.progress import ProgressDisplay


class _TTY(io.StringIO):
    def isatty(self):
        return True


class ProgressDisplayTests(unittest.TestCase):
    def test_progress_renders_percentage_elapsed_and_completion(self):
        stream = _TTY()
        display = ProgressDisplay(stream=stream)
        display.update("Building index", 50, 100)
        display.update("Building index", 100, 100)
        text = stream.getvalue()
        self.assertIn("Building index", text)
        self.assertIn("50.0%", text)
        self.assertIn("100.0%", text)
        self.assertIn("elapsed", text)

    def test_non_tty_output_is_silent(self):
        stream = io.StringIO()
        display = ProgressDisplay(stream=stream)
        display.update("Extracting frames", 1, 2)
        display.finish()
        self.assertEqual(stream.getvalue(), "")

    def test_disabled_output_is_silent_even_for_tty(self):
        stream = _TTY()
        display = ProgressDisplay(enabled=False, stream=stream)
        display.update("Verifying source", 1, 1)
        self.assertEqual(stream.getvalue(), "")

    def test_callbacks_do_not_change_index_or_extraction_result(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            top, dat = generate_synthetic_dataset(root, 8, 4)
            index = root / "test.oxidx"
            index_updates = []
            summary = build_index(top, dat, index, progress_callback=lambda current, total: index_updates.append((current, total)))
            self.assertTrue(index_updates)
            self.assertEqual(index_updates[-1][0], index_updates[-1][1])

            output = root / "selected.dat"
            verify_updates = []
            extract_updates = []
            result = extract_frames(
                top, dat, "1,3", output, index_path=index,
                verification_progress_callback=lambda current, total: verify_updates.append((current, total)),
                progress_callback=lambda current, total: extract_updates.append((current, total)),
            )
            self.assertTrue(verify_updates)
            self.assertTrue(extract_updates)
            self.assertEqual(extract_updates[-1][0], extract_updates[-1][1])
            self.assertEqual(result.bytes_written, output.stat().st_size)
