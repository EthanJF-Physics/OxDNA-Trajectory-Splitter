# OxDNA Trajectory Splitter v8.0.0 — Architecture

## Initial release scope
The initial release provides `validate`, `index`, `extract`, and `benchmark`.
Phase 1 implements strict, read-only scientific-format validation. Indexing and
extraction follow only after this foundation is tested.

## Package layers
- `validation.py`: topology and trajectory structure/numeric validation.
- `trajectory.py`: bounded-memory binary record access and byte offsets.
- `indexing.py`: portable binary frame index, source fingerprints and reuse.
- `extraction.py`: exact byte-range extraction and verified atomic publication.
- `benchmarking.py`: reproducible performance and resource measurements.
- `cli.py`: command-line interface only; no scientific parsing logic.
- `__main__.py`: module entry point.

Low-level modules do not import the CLI. Circular imports are prohibited.

## Strict validation policy
- First topology header value declares a positive nucleotide count.
- Exactly N topology records follow; each has four fields, with integer strand
  and neighbor fields.
- Each trajectory frame has `t`, `b`, and `E` headers in that exact order,
  followed by exactly N nucleotide records.
- `t` has one finite numeric value; `b` and `E` have three each.
- Nucleotide records contain exactly 9 or 15 finite numeric fields, consistently.
- LF and CRLF are accepted, including mixed line endings. Final newline is
  optional only when the final record/frame is complete.
- Blank lines, comments, extra lines, malformed numbers, NaN, infinity, and
  records longer than 4096 bytes are rejected.
- Validation is structural; it does not establish scientific correctness,
  strand connectivity, nucleotide identity correctness, or simulation quality.

## Data safety and indexing
- Topology and trajectory inputs are read-only.
- Index metadata binds to both source files using size and SHA-256, with file
  identity/mtime as supplemental metadata.
- Indexing is a single bounded-memory pass; offsets are unsigned 64-bit
  little-endian values, with N+1 offsets including EOF.
- Candidate indexes are written to unique temporary files, flushed, synced,
  verified, and atomically published. Failed rebuilds preserve old valid indexes.
- Reusing an index verifies both source checksums.
- Concurrent source changes must stop publication of inconsistent results.

## Extraction
- User frame numbers are one-based; ranges are inclusive.
- Multiple non-overlapping ranges can be emitted in requested order into one file.
- Extraction copies original bytes exactly and never rewrites frame data.
- Existing outputs are refused unless overwrite is explicit.
- Output is built in a unique temporary file, checked for count, size, SHA-256,
  and strict validity, then atomically committed.
- Output paths may never resolve to the topology, trajectory, or index, including
  alternate spellings of the path and hard links to those files.
- Extraction requires an existing valid index (all checks of index reuse apply);
  `--build-index` is an explicit opt-in. `--dry-run` never builds an index.
- A contiguous run of selected frames is copied as one byte range. Only the
  source's final frame can lack a trailing line terminator; if it is extracted
  and other frames follow it in the output, one terminator in that frame's own
  line-ending style is inserted and reported. All frame bytes remain exact.
- Without `--overwrite`, publication fails rather than replacing a file that
  appeared during extraction (hard-link publication on POSIX, rename on
  Windows). With `--overwrite`, publication is an atomic replace.
- Free disk space is checked before writing. Source file metadata is re-checked
  before publication.

## CLI exit codes
- 0 success; 2 command-line usage error; 3 validation failure; 4 index problem;
  5 extraction failure (bad range, protected or existing output, failed
  verification, insufficient space); 6 benchmark failure; 7 file-access error.

## Operational safety
- `--dry-run` must be read-only.
- File-creating operations perform preflight describing source paths,
  destination, overwrite behavior, temporary files, and disk requirements.
- Ctrl+C must not publish incomplete files; cleanup removes only process-owned
  temporary files. No user data is deleted to make room.
- Errors have stable codes and location details.

## Performance, compatibility, and release gate
- Standard-library runtime dependencies only; Python >=3.10.
- Windows 11 verification is recorded in the Phase 5 report. Linux sandbox
  verification is recorded separately; formal Ubuntu LTS support is not claimed.
- Streaming memory is bounded; single-threaded processing is the initial design.
- Synthetic stress data is clearly labelled as not scientifically valid and
  kept separate from research data.
- The supplied research files are read-only integration inputs.
- Independent checks verify frame counts, offsets, byte sizes, checksums, and
  extracted content. No critical data-integrity defects may remain at release.

## Benchmarking
- Measures index build (forced rebuild), index reuse (full SHA-256 verification
  of both sources) and extraction (including index verification, copying and
  output verification), with N repeats and median/min/max timings.
- Throughput is reported in MiB/s of bytes processed by each operation.
- Peak memory comes from a separate `tracemalloc` pass (tracemalloc slows
  execution, so it is never mixed into timings); it counts Python allocations
  only.
- Inputs are opened read-only and re-hashed afterwards; a changed input
  invalidates the benchmark. Indexes and outputs live in a unique temporary
  directory removed on success, failure or interruption; pre-existing indexes
  are never used or modified.
- The data kind (`research` or `synthetic`) is mandatory and printed in the
  report header and stored in the JSON report. Synthetic data is generated
  deterministically and is not scientifically valid.
- JSON reports are written atomically, never replace an input file, and refuse
  an existing path unless overwrite is explicit.

## Memory and large files
- Trajectories are only ever streamed: indexing reads line by line and
  extraction copies in 1 MiB chunks. The only data proportional to file size is
  the list of frame offsets (8 bytes per frame), kept in a temporary spill file
  during indexing and memory-mapped when read.
- Every index open or reuse verifies the SHA-256 of both source files, so each
  extraction reads each source file once more in full before copying. This is a
  deliberate integrity-over-speed choice.
- The benchmark report path is validated before any benchmarking starts.

