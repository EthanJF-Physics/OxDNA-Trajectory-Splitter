# Architecture

OxDNA Trajectory Splitter is a command-line tool for validating, indexing, and extracting frames from oxDNA trajectory files. It is designed to preserve source data exactly while processing large files with bounded memory use.

## Package structure

- `validation.py` — validates topology and trajectory structure and numeric fields.
- `trajectory.py` — provides binary record access and byte-offset tracking.
- `indexing.py` — builds and verifies frame indexes.
- `extraction.py` — copies selected frame byte ranges into a new trajectory.
- `benchmarking.py` — measures indexing, reuse and extraction; optional `--measure-memory` profiling measures peak Python memory with tracemalloc.
- `cli.py` — implements the command-line interface.
- `__main__.py` — module entry point.

Parsing and file-handling logic live outside the CLI so the core operations can be tested and reused independently.

## Validation

Validation is strict and structural:

- The topology declares a positive nucleotide count and must contain exactly that many nucleotide records.
- Each trajectory frame contains `t`, `b`, and `E` headers in that order, followed by exactly the topology's nucleotide count.
- `t` contains one finite numeric value; `b` and `E` contain three each.
- Nucleotide records contain consistently either 9 or 15 finite numeric fields.
- LF and CRLF line endings are accepted, including mixed line endings.
- A final newline is optional only when the final record is complete.
- Blank lines, comments, malformed or non-finite numbers, extra records, and records longer than 4096 bytes are rejected.

Validation checks file structure, not scientific correctness or simulation quality.

## Indexing

The index stores the byte offset of every frame plus the end-of-file offset. Offsets are unsigned 64-bit little-endian values.

Indexes are tied to both the topology and trajectory using file metadata and SHA-256 checksums. Reuse verifies the source files before trusting an existing index.

Indexing streams the trajectory rather than loading it into memory. Frame offsets are written to temporary storage and later memory-mapped when the index is read.

New indexes are written to temporary files, verified, and atomically published. A failed rebuild does not replace an existing valid index.

## Extraction

Frame numbers are one-based and ranges are inclusive. Multiple non-overlapping ranges can be written to one output in the requested order.

Extraction copies the original frame bytes rather than parsing and rewriting them. Contiguous selected frames are copied as a single byte range.

If the source's final frame has no trailing line terminator and another selected frame follows it in the output, a single matching line terminator is inserted between the frames.

Extraction requires a valid index unless index creation is explicitly requested. Existing outputs are not replaced unless overwrite is enabled, and output paths are prevented from resolving to the topology, trajectory, or index files.

Output is written to a temporary file, checked, and atomically published. Failed or interrupted extraction must not publish an incomplete output.

## File safety

Source topology and trajectory files are opened read-only. File-creating operations use process-owned temporary files and do not delete user data to make room.

Before publication, the program checks relevant source metadata and verifies generated data. `--dry-run` performs checks and reports the extraction plan without creating files or indexes.

## Large-file behavior

Trajectory processing is streaming and single-threaded. Indexing reads records incrementally, and extraction copies data in fixed-size chunks.

Memory use does not scale with trajectory size except for the frame-offset index, which uses 8 bytes per stored offset and is memory-mapped when read.

For integrity, opening or reusing an index verifies SHA-256 checksums of both source files. This intentionally favors source verification over maximum extraction speed.

## Compatibility

The runtime uses only the Python standard library and requires Python 3.10 or newer. The project has been tested on Windows and Linux environments.
