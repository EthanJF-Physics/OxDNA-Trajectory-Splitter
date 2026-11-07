"""Developer tool (not part of the installed package): compare the frozen v8.1 scanner
with the production scanner on one real or synthetic trajectory.

It never writes next to your data and opens the files read-only. It checks that both
scanners return the identical result tuple and identical offset spool, reports best/median
wall-clock times, and measures the fast-path hit rate (share of nucleotide records the
fast path accepts without the slow path).

Usage (from the repository root):
    python development/tools/compare_scan.py --topology system.top --trajectory traj.dat --repeats 3
    python development/tools/compare_scan.py --topology system.top --trajectory traj.dat --cprofile

Add --label to describe the data (e.g. SYNTHETIC or RESEARCH) in the printed report.
"""
from __future__ import annotations

import argparse
import cProfile
import pathlib
import platform
import pstats
import statistics
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from oxdna_splitter.indexing import _scan_trajectory  # noqa: E402
from oxdna_splitter.validation import FAST_RECORD_MATCHERS, validate_topology  # noqa: E402
import _reference_v81 as v81  # noqa: E402

MIB = 1024 * 1024


def run(scan, path, nucleotides):
    with tempfile.TemporaryFile() as spool:
        started = time.perf_counter()
        result = scan(path, nucleotides, spool)
        elapsed = time.perf_counter() - started
        spool.seek(0)
        return elapsed, result, spool.read()


def hit_rate(path, nucleotides):
    """Fraction of nucleotide records the fast path accepts (frame structure assumed valid)."""
    hits = total = 0
    matcher = None
    with open(path, "rb") as handle:
        while True:
            if not handle.readline():
                break
            handle.readline()
            handle.readline()
            for _ in range(nucleotides):
                raw = handle.readline()
                if matcher is None:
                    matcher = FAST_RECORD_MATCHERS.get(len(raw.split()))
                    total += 1                      # first record always takes the strict path
                    continue
                total += 1
                hits += matcher(raw) is not None
    return hits, total


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--topology", required=True)
    parser.add_argument("--trajectory", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--label", default="UNSPECIFIED")
    parser.add_argument("--cprofile", action="store_true", help="also print a cProfile of the production scanner")
    args = parser.parse_args()

    path = pathlib.Path(args.trajectory)
    nucleotides = validate_topology(args.topology).nucleotide_count
    size = path.stat().st_size
    print(f"data: {args.label}   file: {path.name}  {size:,} bytes   nucleotides/frame: {nucleotides:,}")
    print(f"python {platform.python_version()}  {platform.platform()}")

    old_times, new_times = [], []
    for i in range(args.repeats):
        t_old, r_old, s_old = run(v81.scan_trajectory_v81, path, nucleotides)
        t_new, r_new, s_new = run(_scan_trajectory, path, nucleotides)
        if r_old != r_new or s_old != s_new:
            raise SystemExit(f"MISMATCH on repeat {i + 1}: v8.1 {r_old} vs production {r_new}")
        old_times.append(t_old)
        new_times.append(t_new)
        print(f"  repeat {i + 1}: v8.1 {t_old:8.3f} s   production {t_new:8.3f} s   ({t_old / t_new:.2f}x)")
    print("result tuple, SHA-256 and offset spool identical on every repeat: yes")
    print(f"  frames={r_new[0]} fields={r_new[1]} trajectory sha256={r_new[2]}")
    for label, times in (("v8.1      ", old_times), ("production", new_times)):
        print(f"{label} best {min(times):8.3f} s   median {statistics.median(times):8.3f} s   "
              f"best {size / MIB / min(times):7.1f} MiB/s")
    print(f"speedup (median/median): {statistics.median(old_times) / statistics.median(new_times):.2f}x")
    hits, total = hit_rate(path, nucleotides)
    print(f"fast-path hit rate: {hits:,} / {total:,} nucleotide records = {hits / total:.4%}")

    if args.cprofile:
        with tempfile.TemporaryFile() as spool:
            profile = cProfile.Profile()
            profile.runcall(_scan_trajectory, path, nucleotides, spool)
        pstats.Stats(profile).sort_stats("tottime").print_stats(8)


if __name__ == "__main__":
    main()
