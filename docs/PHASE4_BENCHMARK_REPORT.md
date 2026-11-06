# Phase 4 — Benchmarking report

## Implemented

- `benchmark` CLI command and `oxdna_splitter.benchmarking` module:
  index build, index reuse and extraction benchmarks; repeated runs with
  min/median/max; throughput in MiB/s; file sizes and SHA-256 hashes of both
  inputs and of the extracted output; environment details; JSON report.
- Mandatory `--data-kind research|synthetic` for your own files, or
  `--generate-synthetic NUCLEOTIDES FRAMES`, which is always labelled
  SYNTHETIC. The label appears in the report header, notice line and JSON.
- Inputs are read-only and re-hashed after the run; indexes and outputs are
  created in a temporary directory that is always removed; existing indexes
  are untouched.
- Report file is atomic, refuses existing paths without `--overwrite`, and can
  never replace an input file.

## Test results (observed)

Ubuntu Linux sandbox, Python 3.12.3, `PYTHONPATH=src`:
`python -m unittest discover -s tests` -> **Ran 86 tests, OK**
(65 earlier tests unchanged, plus 21 new benchmarking tests). This has not yet
been run on the Windows computer.

## Example run — SYNTHETIC data, sandbox (NOT research data, NOT Windows)

Command: `benchmark --generate-synthetic 14894 25 --repeats 3`
(14,894 nucleotides, 25 frames, 34,517,229-byte trajectory; the random values
make it larger than the real file). Extraction of frames 1-12
(16,567,175 bytes).

| Operation  | Median time | Throughput | Peak Python memory |
|------------|-------------|------------|--------------------|
| Index build | 2.259 s | 14.57 MiB/s | 1.2 MiB |
| Index reuse | 0.030 s | 1103.68 MiB/s | 2.0 MiB |
| Extraction  | 1.087 s | 14.53 MiB/s | 2.0 MiB |

Index size: 863 bytes. Sources were verified unchanged afterwards.

Reading the numbers: index build and extraction run at about the same speed
because both are limited by strict record-by-record validation in Python, not by
disk copying. Index reuse is fast because it only hashes the files. These are
single-computer timings with warm file caches, not performance guarantees.

## Windows results (Windows 11, Python 3.15.2, 86 tests OK)

REAL RESEARCH DATA (disposable copy; 14,894 nucleotides, 25 frames,
23,090,647-byte trajectory; extraction of frames 1-12, 11,083,055 bytes):

| Operation | Median time | Throughput | Peak Python memory |
|-----------|-------------|------------|--------------------|
| Index build | 2.623 s | 8.4 MiB/s | 1.4 MiB |
| Index reuse | 0.032 s | 701 MiB/s | 2.3 MiB |
| Extraction | 1.224 s | 8.64 MiB/s | 2.3 MiB |

SYNTHETIC data (34,517,229-byte trajectory; frames 1-12, 16,567,175 bytes):
index build 2.842 s, index reuse 0.048 s, extraction 1.425 s; peak Python
memory 1.4 / 2.3 / 2.3 MiB. Sources verified unchanged in both runs. The
synthetic trajectory SHA-256 is identical to the one produced in the Linux
sandbox. Index size differs slightly by platform (936 vs 985 bytes) because the
index stores file paths.

## Not yet done

- Phase 6 (final documentation review and the release ZIP).
