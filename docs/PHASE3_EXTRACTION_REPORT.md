# Phase 3 — Exact frame extraction report

## Implemented

- `extract` CLI command and `oxdna_splitter.extraction` module.
- One-based, inclusive frame ranges (`"1-5,10,20-25"`); requested order is
  preserved; overlapping, duplicate, malformed, zero, reversed, and
  out-of-range ranges are rejected before anything is written.
- Frames are copied as exact byte ranges using the verified binary index, in
  1 MiB chunks (bounded memory).
- Existing outputs are refused unless `--overwrite` is given.
- Output may not be the topology, trajectory, or index (also via alternate path
  spellings or hard links), with or without `--overwrite`.
- Unique temporary output file beside the destination; only that file is
  removed on failure or interruption.
- Verification before publication: size, SHA-256 (re-read from disk versus the
  bytes read from the source), strict structural validation, frame count,
  fields per record; source metadata is re-checked.
- Atomic publication; no-clobber publication when `--overwrite` is not given.
- Free-space preflight; `--dry-run` writes nothing and never builds an index.
- Opt-in `--build-index`; otherwise a missing/stale/corrupt index is refused.

## Design decision to confirm

The source's final frame may lack a trailing line terminator. If it is
extracted *before* other frames, the next frame header would be glued onto its
last record. The implementation inserts one terminator in that frame's own
line-ending style (LF or CRLF) and reports the inserted byte count. All frame
bytes are otherwise untouched. If you would rather refuse such requests, that is
a small change.

## Test results (observed)

Environment for these runs: Ubuntu Linux sandbox, Python 3.12.3, run with
`PYTHONPATH=src`. These runs were NOT on Windows and do not establish Windows or
Ubuntu support; the Windows-specific no-clobber publication branch
(`os.rename`) has not been exercised.

`python -m unittest discover -s tests -v`: **Ran 65 tests, OK**
(validation 11, indexing 9, scaffold 2, extraction 43; the 22 earlier tests
still pass unchanged).

During development two of my own new tests initially failed because their
expected bytes omitted the separator described above; the tests were corrected,
no implementation change was needed.

## Synthetic dataset-sized smoke test (NOT research data)

Synthetic, scientifically meaningless file shaped like the real dataset:
14,894 nucleotides, 235 strands, 25 frames, 9 fields, 34,517,229 bytes (larger
than the real file because of random 6-decimal values). Source files were made
read-only.

- `index`: created, 2.42 s, peak RSS about 18.6 MiB.
- `extract -f "20-25,1-3,10"` (10 frames, 13,807,233 bytes): 1.05 s, peak RSS
  about 20.6 MiB; output SHA-256
  `cfe513c04d3bf3b57efe7832e33e0049c3ca0079017451cd76509befb781c388`,
  identical to an independently computed expected byte string.
- `--dry-run` wrote no file; existing output refused (exit 5); output equal to
  the trajectory refused even with `--overwrite` (exit 5); source SHA-256
  values unchanged; no temporary files left behind.
- Timings are single runs on a sandbox, not formal benchmarks (Phase 4).

## Not yet done

Phase 4 benchmarking, Phase 5 expanded safety campaign (large-file memory
tests, more interruption scenarios, testing on your real files via disposable
copies), Phase 6 documentation and release ZIP. Verification on your Windows
machine is still outstanding.
