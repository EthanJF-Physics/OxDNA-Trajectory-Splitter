# Phase 2 — Binary indexing implementation report

## Implemented

- Versioned binary index with an eight-byte magic signature and fixed-size header.
- Compact JSON metadata with source paths, file sizes, modification metadata,
  device/inode metadata, SHA-256 hashes, nucleotide count, frame count, and
  nucleotide-record field count.
- Little-endian unsigned 64-bit offsets with N+1 entries, including EOF.
- One trajectory pass performs strict structural/numeric validation, computes
  the trajectory SHA-256, and streams offsets to a temporary spool file. RAM
  usage does not grow with the number of frames.
- Index metadata and offset array each have SHA-256 checksums.
- Existing indexes are memory-mapped and checked before reuse. Both source
  files are fully hashed before an existing index is trusted.
- Stale/corrupt indexes are rebuilt. A candidate index is verified before
  atomic replacement; failed builds leave the previous index untouched.
- `index` CLI command with optional custom index path and `--rebuild-index`.

## Safety and scope notes

- Source topology and trajectory files are read-only.
- The default index path is `<trajectory filename>.oxidx` in the trajectory
  directory.
- The index stores frame boundaries as byte offsets; it does not rewrite or
  normalize trajectory data.
- The implementation checks source metadata before and after processing and
  again before publication. This detects ordinary concurrent changes but is
  not a filesystem-level lock against a hostile writer racing the final check.
- The test fixtures are synthetic and are not scientifically valid research
  data.

## Verification performed in the build environment

- Unit tests cover index creation, exact frame ranges, N+1/EOF offset behavior,
  valid-index reuse, changed-source rebuild, direct source-mismatch rejection,
  corruption recovery, truncated-index rejection, failed-rebuild preservation,
  source-file non-modification, and refusal to overwrite a source.
- The complete local unit-test suite is run before packaging.
- Real reference data integration still needs to be run on the user's Windows
  machine; this environment does not have access to their Desktop files.
