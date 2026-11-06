# Phase 5 — Safety testing report

All fixtures are synthetic and disposable. No research file was modified by any
test. The Windows measurements below used disposable copies in
`oxdna-scratch`; originals were hash-checked before and after.

## Automated test suite

`python -m unittest discover -s tests`

- Ubuntu Linux sandbox, Python 3.12.3: **Ran 112 tests, OK**.
- Windows 11, Python 3.15.2: **Ran 112 tests, OK** (Phase 5 package;
  result reported by the project owner from the Windows PC on 2026-11-06).

New in Phase 5 (`tests/test_safety.py`, 25 tests, plus 1 benchmark test):

| Area | What is verified |
|------|------------------|
| Corrupt indexes | Flipping any single byte of an index is rejected (every position); every truncation length is rejected; appended garbage rejected; empty index rebuilt; extraction refuses damaged indexes and writes nothing |
| Stale indexes | Changed topology, same-size changed trajectory content (caught by SHA-256), moved files (index is location-bound) |
| Interrupted operations | Ctrl+C during scanning, during candidate verification, and failure at publication: no temp file left, previous index preserved, nothing published; source modified during indexing |
| Invalid inputs | Invalid/empty trajectory or topology, wrong nucleotide count, source deleted after indexing; CLI exit codes 3/4 |
| Formats | CRLF, 15-field, CRLF+15-field, single-nucleotide systems: byte-exact in several range orders |
| Many frames | 3,000 frames: multi-range ordered extraction and full-range identity with the source |
| Immutability | Read-only sources through validate, index, extract and benchmark: hashes and modification times unchanged, no temp files |
| Bounded memory | Python peak memory differs by under 1.5 MiB between files differing 30x in size, and stays under 4 MiB |
| Fail-fast | A benchmark report path that exists or is an input file is refused before any benchmarking |

Two issues were found and fixed during this phase:

1. Two of my first-draft tests had defects (a cleanup that ran after the
   temporary folder was deleted; a memory test that was needlessly slow). No
   implementation change was needed for those.
2. A real usability defect: the benchmark only checked the report path after
   finishing, so a mistyped or existing report path wasted the whole run. It is
   now checked first. Found from a real Windows run.

## Large-file memory measurement (SYNTHETIC, Linux sandbox)

Peak process memory (RSS) measured around the real command-line program, with
read-only-style verification afterwards:

| Trajectory | Index peak RSS | Extract peak RSS |
|------------|----------------|------------------|
| 34.5 MB, 25 frames | 18.6 MiB | 20.6 MiB |
| 414.2 MB, 300 frames | 19.8 MiB | 21.6 MiB |

A 12x larger file raised peak memory by about 1 MiB. In the large run,
indexing took 27.2 s; extracting frames `250-300,1-20,150` (72 frames,
99,410,340 bytes) took 7.2 s, and the output was byte-identical to an
independent plain-Python slice of the source. The source hash was unchanged
and no temp files remained. Not yet measured: files beyond about 0.4 GB, or any
large-file measurement on Windows.

## Real-data checks (Windows, disposable copies)

- Extracting frames `20-25,1-3,10` and `25,1`: outputs verified byte-identical
  to the corresponding frames of the source by an independent plain-Python
  check; tool SHA-256 matched PowerShell `Get-FileHash`.
- Refusals for an existing output and for an output equal to the trajectory
  behaved as designed; original files had identical hashes before and after.
- Benchmark on real data (Windows, Python 3.15.2, frames 1-12): index build
  median 2.623 s, index reuse 0.032 s, extraction 1.224 s; sources verified
  unchanged. The extraction SHA-256 (`72fbde2e...`) is identical to the one
  produced on Linux for the same frames.
- Synthetic data is generated identically on Windows and Linux (same SHA-256).

## Known limits

- The index is bound to the absolute file locations; moving files requires a
  new index.
- Every extraction fully reads and hashes both source files first, which costs
  time proportional to trajectory size.
- On POSIX filesystems without hard links, no-clobber publication falls back to
  a check-then-replace with a very small race window.
- Linux sandbox testing is recorded separately from Windows testing. These
  results do not constitute a formal Ubuntu LTS release test, so Ubuntu LTS
  support is not claimed.
