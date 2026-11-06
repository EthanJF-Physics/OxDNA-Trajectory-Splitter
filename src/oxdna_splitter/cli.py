"""Command-line interface for OxDNA Trajectory Splitter."""
from __future__ import annotations

import argparse
import sys

from .validation import ValidationError, validate_files
from .indexing import IndexErrorBase, build_index, default_index_path
from .extraction import ExtractionError, extract_frames, plan_extraction
from .benchmarking import (
    BenchmarkError, DATA_KINDS, check_report_path, format_report_text,
    generate_synthetic_dataset, run_benchmark, write_report,
)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oxdna-splitter",
        description="Strictly validate, index, and extract oxDNA trajectory frames.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser(
        "validate", help="Read-only validation of a topology and trajectory."
    )
    validate_parser.add_argument("--topology", "-t", required=True, help="Path to .top topology.")
    validate_parser.add_argument("--trajectory", "-d", required=True, help="Path to .dat trajectory.")
    validate_parser.add_argument("--quiet", action="store_true", help="Print only the final result.")
    validate_parser.add_argument("--verbose", action="store_true", help="Print detailed metadata.")

    index_parser = subparsers.add_parser(
        "index", help="Build or verify a binary frame index."
    )
    index_parser.add_argument("--topology", "-t", required=True, help="Path to .top topology.")
    index_parser.add_argument("--trajectory", "-d", required=True, help="Path to .dat trajectory.")
    index_parser.add_argument("--index", help="Optional index output path (default: trajectory.dat.oxidx).")
    index_parser.add_argument("--rebuild-index", action="store_true", help="Rebuild even if an existing index is valid.")
    index_parser.add_argument("--quiet", action="store_true", help="Print only the final result.")

    extract_parser = subparsers.add_parser(
        "extract", help="Extract selected frames exactly into one new trajectory file."
    )
    extract_parser.add_argument("--topology", "-t", required=True, help="Path to .top topology.")
    extract_parser.add_argument("--trajectory", "-d", required=True, help="Path to .dat trajectory.")
    extract_parser.add_argument("--frames", "-f", required=True, help="One-based inclusive frames, e.g. \"1-5,10,20-25\".")
    extract_parser.add_argument("--output", "-o", required=True, help="Path of the new combined trajectory file.")
    extract_parser.add_argument("--index", help="Index path (default: trajectory.dat.oxidx).")
    extract_parser.add_argument("--build-index", action="store_true", help="Build or refresh the index first if needed.")
    extract_parser.add_argument("--overwrite", action="store_true", help="Replace the output file if it already exists.")
    extract_parser.add_argument("--dry-run", action="store_true", help="Check everything and report the plan; write nothing.")
    extract_parser.add_argument("--quiet", action="store_true", help="Print only the final result.")

    bench_parser = subparsers.add_parser(
        "benchmark", help="Measure index build, index reuse and extraction speed (read-only on inputs)."
    )
    bench_parser.add_argument("--topology", "-t", help="Path to .top topology.")
    bench_parser.add_argument("--trajectory", "-d", help="Path to .dat trajectory.")
    bench_parser.add_argument("--data-kind", choices=DATA_KINDS, help="REQUIRED with --topology/--trajectory: is this real research data or synthetic test data?")
    bench_parser.add_argument("--generate-synthetic", nargs=2, type=int, metavar=("NUCLEOTIDES", "FRAMES"), help="Generate and benchmark a SYNTHETIC dataset instead of using your files.")
    bench_parser.add_argument("--frames", "-f", help="Frames to extract (default: first half of the frames).")
    bench_parser.add_argument("--repeats", type=int, default=3, help="Timing repeats, 1-50 (default 3).")
    bench_parser.add_argument("--work-dir", help="Directory for temporary indexes/outputs (default: system temp).")
    bench_parser.add_argument("--report", help="Also save the full report as JSON to this new file.")
    bench_parser.add_argument("--overwrite", action="store_true", help="Allow replacing an existing --report file.")
    return parser


def _run_benchmark(args, parser) -> int:
    generating = args.generate_synthetic is not None
    if generating and (args.topology or args.trajectory or args.data_kind):
        parser.error("--generate-synthetic cannot be combined with --topology, --trajectory or --data-kind.")
    if not generating and not (args.topology and args.trajectory):
        parser.error("Give --topology and --trajectory (with --data-kind), or use --generate-synthetic.")
    if not generating and not args.data_kind:
        parser.error("--data-kind research|synthetic is required, so reports are never mislabelled.")
    import contextlib
    import tempfile
    try:
        if args.report:
            from pathlib import Path
            early = () if generating else (
                ("topology", Path(args.topology).resolve()), ("trajectory", Path(args.trajectory).resolve()),
            )
            check_report_path(args.report, early, overwrite=args.overwrite)  # fail fast, before any work
        synth_context = (
            tempfile.TemporaryDirectory(prefix="oxdna-synth-", dir=args.work_dir)
            if generating else contextlib.nullcontext()
        )
        with synth_context as synth_dir:
            if generating:
                top, dat = generate_synthetic_dataset(synth_dir, *args.generate_synthetic)
                kind = "synthetic"
            else:
                top, dat, kind = args.topology, args.trajectory, args.data_kind
            report = run_benchmark(
                top, dat, data_kind=kind, frames_spec=args.frames,
                repeats=args.repeats, work_dir=args.work_dir,
            )
            print(format_report_text(report))
            if args.report:
                from pathlib import Path
                protected = (("topology", Path(top).resolve()), ("trajectory", Path(dat).resolve()))
                saved = write_report(report, args.report, protected, overwrite=args.overwrite)
                print(f"\nReport saved:          {saved}")
        return 0
    except BenchmarkError as exc:
        print(f"BENCHMARK FAILED: {exc}", file=sys.stderr)
        return 6
    except ExtractionError as exc:
        print(f"BENCHMARK FAILED [{exc.code}]: {exc.message}", file=sys.stderr)
        return 5
    except IndexErrorBase as exc:
        print(f"BENCHMARK FAILED [INDEX_PROBLEM]: {exc}", file=sys.stderr)
        return 4
    except OSError as exc:
        print(f"BENCHMARK FAILED [FILE_ACCESS_ERROR]: {exc}", file=sys.stderr)
        return 7


def _format_ranges(ranges) -> str:
    return ", ".join(f"{r.start}" if r.start == r.end else f"{r.start}-{r.end}" for r in ranges)


def _run_extract(args) -> int:
    try:
        if args.dry_run:
            plan = plan_extraction(
                args.topology, args.trajectory, args.frames, args.output,
                index_path=args.index, overwrite=args.overwrite,
            )
        else:
            result = extract_frames(
                args.topology, args.trajectory, args.frames, args.output,
                index_path=args.index, overwrite=args.overwrite,
                build_index_if_needed=args.build_index,
            )
    except ExtractionError as exc:
        print(f"EXTRACTION FAILED [{exc.code}]", file=sys.stderr)
        print(exc.message, file=sys.stderr)
        return 5
    except IndexErrorBase as exc:
        print(f"EXTRACTION FAILED [INDEX_PROBLEM]: {exc}", file=sys.stderr)
        print("Run the 'index' command with --rebuild-index, or pass --build-index.", file=sys.stderr)
        return 4
    except OSError as exc:
        print(f"EXTRACTION FAILED [FILE_ACCESS_ERROR]: {exc}", file=sys.stderr)
        return 7
    if args.dry_run:
        print("DRY RUN OK - no files were written")
        if not args.quiet:
            print(f"Frames requested:      {_format_ranges(plan.ranges)} ({plan.frames_selected:,} of {plan.source_frame_count:,})")
            print(f"Output:                {plan.output_path}")
            print(f"Output exists:         {'yes (would be replaced)' if plan.output_exists else 'no'}")
            print(f"Expected size:         {plan.expected_bytes:,} bytes")
            print(f"Separator inserted:    {len(plan.separator) if plan.separator_after_range is not None else 0} byte(s)")
        return 0
    print("EXTRACTION COMPLETE")
    if not args.quiet:
        print(f"Output:                {result.output_path}")
        print(f"Frames extracted:      {result.frames_extracted:,} of {result.source_frame_count:,} ({_format_ranges(result.ranges)})")
        print(f"Output size:           {result.bytes_written:,} bytes")
        print(f"Output SHA-256:        {result.sha256}")
        print(f"Separator inserted:    {result.separator_bytes_inserted} byte(s)")
        print(f"Replaced existing:     {'yes' if result.overwritten else 'no'}")
        print("Verification:          size, SHA-256, strict validation, frame count - all passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    if args.command == "validate":
        try:
            summary = validate_files(args.topology, args.trajectory)
        except ValidationError as exc:
            print(f"VALIDATION FAILED [{exc.code}]", file=sys.stderr)
            print(str(exc), file=sys.stderr)
            return 3
        except OSError as exc:
            print(f"VALIDATION FAILED [FILE_ACCESS_ERROR]: {exc}", file=sys.stderr)
            return 7
        print("VALIDATION PASSED")
        if not args.quiet:
            print(f"Topology:              {summary.topology.path}")
            print(f"Trajectory:            {summary.trajectory_path}")
            print(f"Nucleotides:           {summary.nucleotide_count:,}")
            print(f"Frames:                {summary.frame_count:,}")
            print(f"Fields per nucleotide: {summary.nucleotide_fields}")
            print(f"Trajectory size:       {summary.trajectory_size_bytes:,} bytes")
            print(f"Newline styles:        {', '.join(summary.newline_styles)}")
            if args.verbose:
                print(f"Topology size:         {summary.topology.size_bytes:,} bytes")
                print(f"Topology strands:      {summary.topology.strand_count}")
                print(f"First frame time:      {summary.first_frame_time:g}")
                print(f"Last frame time:       {summary.last_frame_time:g}")
                print("Validation mode:       strict; read-only")
        return 0
    if args.command == "index":
        try:
            result = build_index(
                args.topology, args.trajectory, args.index, rebuild=args.rebuild_index
            )
        except IndexErrorBase as exc:
            print(f"INDEX FAILED: {exc}", file=sys.stderr)
            return 4
        except OSError as exc:
            print(f"INDEX FAILED [FILE_ACCESS_ERROR]: {exc}", file=sys.stderr)
            return 7
        print("INDEX READY" if result.reused else "INDEX CREATED")
        if not args.quiet:
            print(f"Index:                 {result.index_path}")
            print(f"Topology:              {result.topology_path}")
            print(f"Trajectory:            {result.trajectory_path}")
            print(f"Nucleotides:           {result.nucleotide_count:,}")
            print(f"Frames:                {result.frame_count:,}")
            print(f"Fields per nucleotide: {result.nucleotide_fields}")
            print(f"Trajectory size:       {result.trajectory_size_bytes:,} bytes")
            print(f"Topology SHA-256:      {result.topology_sha256}")
            print(f"Trajectory SHA-256:    {result.trajectory_sha256}")
            print(f"Index reused:          {'yes' if result.reused else 'no'}")
        return 0
    if args.command == "extract":
        return _run_extract(args)
    if args.command == "benchmark":
        return _run_benchmark(args, parser)
    parser.error("Unknown command.")
    return 2
