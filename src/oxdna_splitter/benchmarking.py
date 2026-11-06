"""Reproducible performance measurements for indexing and extraction.

Benchmarks never modify the input files and never touch an existing index: all
indexes and extracted outputs live in a unique temporary directory that is
removed afterwards. Every report states whether the data is SYNTHETIC test data
or REAL RESEARCH data; the caller must say which, it is never guessed.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import random
import statistics
import sys
import tempfile
import time
import tracemalloc

from . import __version__
from .extraction import ExtractionError, _check_output_path, _publish_no_clobber, extract_frames
from .indexing import _fsync_directory, _hash_file, _write_all, build_index

REPORT_SCHEMA = 1
DATA_KINDS = ("research", "synthetic")
_MIB = 1024 * 1024
_NOTICES = {
    "synthetic": "SYNTHETIC test data: randomly generated, scientifically meaningless; "
                 "timings describe software behavior only.",
    "research": "REAL RESEARCH DATA: opened read-only and verified unchanged; "
                "results describe this dataset and this computer only.",
}


class BenchmarkError(Exception):
    """A benchmark could not be completed or its safety checks failed."""


def generate_synthetic_dataset(
    directory: str | Path, nucleotides: int, frames: int, *, seed: int = 1, progress_callback=None
) -> tuple[Path, Path]:
    """Write a deterministic SYNTHETIC topology/trajectory pair (not scientific data)."""
    if not isinstance(nucleotides, int) or not isinstance(frames, int) or nucleotides < 2 or frames < 1:
        raise BenchmarkError("Synthetic data needs at least 2 nucleotides and 1 frame.")
    folder = Path(directory)
    top, dat = folder / "synthetic.top", folder / "synthetic.dat"
    strand_length = 60
    strands = -(-nucleotides // strand_length)
    with top.open("w", encoding="ascii", newline="\n") as handle:
        handle.write(f"{nucleotides} {strands}\n")
        for i in range(nucleotides):
            position = i % strand_length
            n3 = i - 1 if position else -1
            n5 = i + 1 if position != strand_length - 1 and i + 1 < nucleotides else -1
            handle.write(f"{i // strand_length + 1} {'ACGT'[i % 4]} {n3} {n5}\n")
    rng = random.Random(seed)
    with dat.open("w", encoding="ascii", newline="\n") as handle:
        for frame in range(frames):
            lines = [f"t = {frame * 1000}", "b = 100 100 100", "E = -1.5 0.1 -1.4"]
            for _ in range(nucleotides):
                lines.append(" ".join(f"{rng.uniform(-50, 50):.6f}" for _ in range(9)))
            handle.write("\n".join(lines) + "\n")
            if progress_callback is not None:
                progress_callback(frame + 1, frames)
    return top, dat


def _timed(function):
    started = time.perf_counter()
    value = function()
    return time.perf_counter() - started, value


def _peak_python_memory(function) -> int:
    tracemalloc.start()
    try:
        function()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def _summary(seconds: list[float], bytes_processed: int) -> dict:
    median = statistics.median(seconds)
    return {
        "seconds": [round(s, 6) for s in seconds],
        "min_seconds": round(min(seconds), 6),
        "median_seconds": round(median, 6),
        "max_seconds": round(max(seconds), 6),
        "bytes_processed": bytes_processed,
        "median_throughput_mib_per_s": round(bytes_processed / _MIB / median, 2) if median > 0 else None,
    }


def _file_fact(path: Path, digest: str) -> dict:
    return {"name": path.name, "size_bytes": path.stat().st_size, "sha256": digest}


def run_benchmark(
    topology_path: str | Path,
    trajectory_path: str | Path,
    *,
    data_kind: str,
    frames_spec: str | None = None,
    repeats: int = 3,
    work_dir: str | Path | None = None,
    progress_callback=None,
) -> dict:
    """Benchmark index build, index reuse and extraction; return a report dict."""
    if data_kind not in DATA_KINDS:
        raise BenchmarkError(f"data_kind must be one of {DATA_KINDS}; say explicitly whether the data is synthetic or research data.")
    if not isinstance(repeats, int) or not 1 <= repeats <= 50:
        raise BenchmarkError("repeats must be a whole number from 1 to 50.")
    topology = Path(topology_path).resolve()
    trajectory = Path(trajectory_path).resolve()
    if work_dir is not None and not Path(work_dir).is_dir():
        raise BenchmarkError(f"Work directory does not exist: {work_dir}")

    top_hash = _hash_file(topology)
    traj_hash = (_hash_file(trajectory, progress_callback=lambda current, total: progress_callback("Verifying source", current, total)) if progress_callback else _hash_file(trajectory))
    top_size, traj_size = topology.stat().st_size, trajectory.stat().st_size

    build_s: list[float] = []
    reuse_s: list[float] = []
    extract_s: list[float] = []
    extraction_facts: set[tuple[int, str, int]] = set()
    with tempfile.TemporaryDirectory(prefix="oxdna-bench-", dir=work_dir) as scratch_name:
        scratch = Path(scratch_name)
        index = scratch / "bench.oxidx"
        spec = frames_spec
        summary = None
        for run in range(repeats):
            seconds, summary = _timed(lambda: build_index(topology, trajectory, index, rebuild=True, progress_callback=(lambda current, total: progress_callback(f"Building index {run + 1}/{repeats}", current, total)) if progress_callback else None))
            build_s.append(seconds)
            if spec is None:
                spec = f"1-{max(1, summary.frame_count // 2)}"
            seconds, reused = _timed(lambda: build_index(topology, trajectory, index, progress_callback=(lambda current, total: progress_callback(f"Verifying source {run + 1}/{repeats}", current, total)) if progress_callback else None))
            if not reused.reused:
                raise BenchmarkError("The freshly built index was not reused; benchmark aborted.")
            reuse_s.append(seconds)
            output = scratch / f"extract_{run}.dat"
            seconds, result = _timed(lambda: extract_frames(topology, trajectory, spec, output, index_path=index, verification_progress_callback=(lambda current, total: progress_callback(f"Verifying source {run + 1}/{repeats}", current, total)) if progress_callback else None, progress_callback=(lambda current, total: progress_callback(f"Extracting frames {run + 1}/{repeats}", current, total)) if progress_callback else None))
            extract_s.append(seconds)
            extraction_facts.add((result.frames_extracted, result.sha256, result.bytes_written))
            output.unlink()
        if len(extraction_facts) != 1:
            raise BenchmarkError("Repeated extractions produced different output; benchmark aborted.")
        frames_selected, out_sha, out_bytes = next(iter(extraction_facts))
        index_size = index.stat().st_size

        # One separate pass for memory, because tracemalloc slows execution.
        peak_build = _peak_python_memory(lambda: build_index(topology, trajectory, index, rebuild=True))
        peak_reuse = _peak_python_memory(lambda: build_index(topology, trajectory, index))
        probe = scratch / "extract_memory.dat"
        peak_extract = _peak_python_memory(lambda: extract_frames(topology, trajectory, spec, probe, index_path=index))
        probe.unlink()

    if _hash_file(topology) != top_hash or _hash_file(trajectory) != traj_hash:
        raise BenchmarkError("A source file changed during the benchmark; results are invalid.")

    return {
        "schema": REPORT_SCHEMA,
        "tool": "oxdna-trajectory-splitter",
        "version": __version__,
        "data_kind": data_kind,
        "data_notice": _NOTICES[data_kind],
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": {
            "python": sys.version.split()[0],
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
        },
        "sources": {
            "topology": _file_fact(topology, top_hash),
            "trajectory": _file_fact(trajectory, traj_hash),
            "nucleotides": summary.nucleotide_count,
            "frames": summary.frame_count,
            "fields_per_nucleotide": summary.nucleotide_fields,
        },
        "sources_unchanged_after_benchmark": True,
        "index": {"size_bytes": index_size},
        "extraction": {
            "frames_spec": spec,
            "frames_selected": frames_selected,
            "output_bytes": out_bytes,
            "output_sha256": out_sha,
        },
        "repeats": repeats,
        "results": {
            "index_build": _summary(build_s, traj_size),
            "index_reuse": _summary(reuse_s, traj_size + top_size),
            "extraction": _summary(extract_s, out_bytes),
        },
        "peak_python_memory_bytes": {
            "index_build": peak_build,
            "index_reuse": peak_reuse,
            "extraction": peak_extract,
            "method": "tracemalloc; Python-allocated memory only; excludes memory-mapped index pages and the OS file cache",
        },
        "notes": [
            "Timings are wall-clock and include operating-system file caching; the first repeat may be slower than later ones.",
            "index_build processes the trajectory once; index_reuse verifies the SHA-256 of topology and trajectory; extraction includes index verification, copying and output verification.",
            "Indexes and outputs were written to a temporary directory and removed afterwards.",
        ],
    }


def format_report_text(report: dict) -> str:
    src, res, mem = report["sources"], report["results"], report["peak_python_memory_bytes"]
    kind = report["data_kind"].upper()
    lines = [
        f"BENCHMARK REPORT - {kind} DATA",
        report["data_notice"],
        "",
        f"Created (UTC):         {report['created_utc']}",
        f"Software version:      {report['version']}",
        f"Python:                {report['environment']['python']} ({report['environment']['implementation']})",
        f"Platform:              {report['environment']['platform']}",
        f"Topology:              {src['topology']['name']}  {src['topology']['size_bytes']:,} bytes  SHA-256 {src['topology']['sha256']}",
        f"Trajectory:            {src['trajectory']['name']}  {src['trajectory']['size_bytes']:,} bytes  SHA-256 {src['trajectory']['sha256']}",
        f"Nucleotides / frames:  {src['nucleotides']:,} / {src['frames']:,}",
        f"Index size:            {report['index']['size_bytes']:,} bytes",
        f"Extraction:            frames {report['extraction']['frames_spec']} ({report['extraction']['frames_selected']:,} frames, {report['extraction']['output_bytes']:,} bytes)",
        f"Extraction SHA-256:    {report['extraction']['output_sha256']}",
        f"Repeats:               {report['repeats']}",
        "",
    ]
    for key, label in (("index_build", "Index build"), ("index_reuse", "Index reuse"), ("extraction", "Extraction")):
        r = res[key]
        lines.append(
            f"{label:<12} median {r['median_seconds']:.3f} s (min {r['min_seconds']:.3f}, max {r['max_seconds']:.3f})"
            f"  {r['median_throughput_mib_per_s']} MiB/s  peak Python memory {mem[key] / _MIB:.1f} MiB"
        )
    lines += ["", "Sources verified unchanged after the benchmark: yes", "Notes:"]
    lines += [f"  - {note}" for note in report["notes"]]
    lines.append(f"  - Memory: {mem['method']}.")
    return "\n".join(lines)


def check_report_path(report_path: str | Path, protected: tuple[tuple[str, Path], ...], *, overwrite: bool = False) -> Path:
    """Refuse unsafe or existing report paths. Call before benchmarking so no time is wasted."""
    destination = Path(report_path).resolve()
    try:
        _check_output_path(destination, protected, overwrite)
    except ExtractionError as exc:
        raise BenchmarkError(exc.message) from exc
    return destination


def write_report(report: dict, report_path: str | Path, protected: tuple[tuple[str, Path], ...], *, overwrite: bool = False) -> Path:
    """Write the JSON report atomically; never replace a protected or existing file by accident."""
    destination = check_report_path(report_path, protected, overwrite=overwrite)
    payload = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            _write_all(handle, payload)
            handle.flush()
            os.fsync(handle.fileno())
        if overwrite:
            os.replace(temp, destination)
        else:
            try:
                _publish_no_clobber(temp, destination)
            except FileExistsError as exc:
                raise BenchmarkError(f"Report path appeared during the run and was not changed: {destination}") from exc
        _fsync_directory(destination.parent)
    finally:
        temp.unlink(missing_ok=True)
    return destination
