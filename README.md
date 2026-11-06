# OxDNA Trajectory Splitter

A Python tool for strict validation, indexing, and exact frame extraction from
large oxDNA trajectory files.

**Version:** 8.0.0  
**Development status:** Phases 1-6 complete for this release candidate.
The implementation has 112 passing tests in the Linux sandbox; the project
owner also reports 112 passing tests on Windows 11. See the phase reports for
the exact environments and limits. This is a release candidate, not a claim
of formal Ubuntu LTS support or permission to redistribute.

## Current capability

The `validate` command reads a topology and trajectory without modifying either
file. It checks the topology nucleotide count, strict `t` / `b` / `E` frame
headers, nucleotide record counts, supported numeric field counts (9 or 15),
finite numeric values, line endings, blank records, and the 4096-byte record
limit.

Validation is structural. It does not prove scientific correctness, verify
strand connectivity, or judge simulation quality.

## Project layout

```text
oxdna-trajectory-splitter/
├── README.md
├── LICENSE-STATUS.md
├── pyproject.toml
├── docs/
│   └── ARCHITECTURE.md
├── src/oxdna_splitter/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── validation.py
│   ├── trajectory.py
│   ├── indexing.py
│   ├── extraction.py
│   └── benchmarking.py
├── tests/
│   ├── README.md
│   ├── test_project_scaffold.py
│   ├── test_validation.py
│   ├── test_indexing.py
│   ├── test_extraction.py
│   ├── test_benchmarking.py
│   └── test_safety.py
└── releases/
    └── README.md
```

## Requirements

- Python 3.10 or newer.
- No third-party runtime dependencies.

## Getting Started — First-Time Users

New to oxDNA Trajectory Splitter? Follow these steps to install the program and extract frames from your first trajectory.

### 1. Download the project

Download the ZIP archive from the GitHub repository using the green **Code → Download ZIP** button.

Extract the ZIP archive to a convenient location on your computer.

### 2. Install Python

Python 3.10 or newer is required.

Download Python from [python.org](https://www.python.org/downloads/).

On Windows, enable **Add Python to PATH** during installation.

### 3. Install oxDNA Trajectory Splitter

Open PowerShell (Windows) or a terminal (Linux/macOS) inside the extracted project directory.

**Windows PowerShell:**

Create a virtual environment:

```powershell
py -m venv .venv
```

Install the program:

```powershell
.\.venv\Scripts\python.exe -m pip install .
```

**Linux / macOS:**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
```

No additional third-party runtime dependencies are required.

### 4. Check the installation

**Windows:**

```powershell
.\.venv\Scripts\oxdna-splitter.exe --help
```

**Linux / macOS:**

```bash
.venv/bin/oxdna-splitter --help
```

The help menu lists the four available commands:

- `validate` — validate topology and trajectory files.
- `index` — build or verify a binary frame index.
- `extract` — extract selected frames into a new trajectory.
- `benchmark` — measure indexing and extraction performance.

### 5. Prepare your oxDNA files

You need two files from your oxDNA simulation:

- A topology file (`.top`), describing the simulated system.
- A trajectory file (`.dat`), containing the simulation frames.

For example:

```text
moon.top
slice.dat
```

Keep your original simulation files unchanged.

### 6. Validate your files

Before extracting anything, check that your topology and trajectory are structurally compatible.

**Windows PowerShell:**

```powershell
.\.venv\Scripts\oxdna-splitter.exe validate `
  --topology "$env:USERPROFILE\Desktop\moon.top" `
  --trajectory "$env:USERPROFILE\Desktop\slice.dat" `
  --verbose
```

Replace the example filenames and paths with the locations of your own files.

A successful validation reports `VALIDATION PASSED`.

### 7. Extract your first frames

For example, to extract frames 1 through 10:

```powershell
.\.venv\Scripts\oxdna-splitter.exe extract `
  --topology "$env:USERPROFILE\Desktop\moon.top" `
  --trajectory "$env:USERPROFILE\Desktop\slice.dat" `
  --frames "1-10" `
  --output "$env:USERPROFILE\Desktop\moon_extracted.dat" `
  --build-index
```

The program builds or refreshes the required index, extracts the selected frames, verifies the new trajectory, and publishes the output.

Your original trajectory is not modified.

### 8. Extract nonconsecutive frames

You can also combine multiple frame ranges into one new trajectory.

For example:

```powershell
.\.venv\Scripts\oxdna-splitter.exe extract `
  --topology "$env:USERPROFILE\Desktop\moon.top" `
  --trajectory "$env:USERPROFILE\Desktop\slice.dat" `
  --frames "1-3,10,15-18,25" `
  --output "$env:USERPROFILE\Desktop\moon_selected.dat"
```

Frame numbers are one-based and ranges are inclusive. Selected ranges must not overlap.

### 9. Verify your output

After extraction, the program reports:

- Number of frames extracted.
- Output file location and size.
- Output SHA-256 hash.
- Strict structural validation result.
- Frame count verification result.

An `EXTRACTION COMPLETE` message with all verification checks passed indicates that the new trajectory was successfully created and verified.

**Important:** Keep your original topology and trajectory files as your source data. This software performs structural validation and frame extraction; it does not establish scientific correctness or simulation quality.

## Validate a dataset

```bash
oxdna-splitter validate --topology path/to/system.top --trajectory path/to/trajectory.dat
```

Or run it as a Python module:

```bash
python -m oxdna_splitter validate --topology path/to/system.top --trajectory path/to/trajectory.dat
```

Use `--verbose` for additional metadata or `--quiet` for a one-line success
message. Validation is read-only.

## Scientific format and safety policy

The supported initial format and strict validation policy are documented in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Do not use this software as a
substitute for preserving original simulation data. Keep original `.top` and
`.dat` files unchanged and make working copies before any external processing.

**Platform scope:** Windows 11 verification is recorded in the Phase 5 report.
Linux sandbox tests are also recorded, but they are not a formal Ubuntu LTS
release test. Ubuntu LTS support is therefore not claimed.

## Build a frame index

Create or safely reuse a binary index beside a trajectory:

```powershell
python -m oxdna_splitter index --topology "moon.top" --trajectory "slice.dat"
```

By default, the index is named `slice.dat.oxidx`. To force a rebuild:

```powershell
python -m oxdna_splitter index --topology "moon.top" --trajectory "slice.dat" --rebuild-index
```

The index is a cache bound to both source files by SHA-256. Existing indexes
are checked before reuse; a stale or damaged index is rebuilt using a temporary
file and atomic replacement. Source topology and trajectory files are opened
read-only and are never modified by indexing.

## Extract frames

Extract selected frames into one new trajectory file. Frame numbers are
one-based and ranges are inclusive; ranges are written in the order you list
them and must not overlap.

```powershell
python -m oxdna_splitter extract --topology "moon.top" --trajectory "slice.dat" --frames "20-25,1-3,10" --output "selected.dat"
```

Extraction uses the existing index (`slice.dat.oxidx`) and refuses to run if it
is missing, stale, or damaged; run the `index` command first, or add
`--build-index` to build or refresh it as part of the command. Useful options:

- `--dry-run` checks everything and reports the plan without writing any file.
- `--overwrite` allows replacing an existing output file. Without it, an
  existing output is never touched.
- `--index PATH` uses a non-default index location.

Safety behavior: the original topology, trajectory, and index are never
modified, and the output path may never be any of them (including through a
different spelling of the path or a hard link). The output is written to a
unique temporary file beside the destination, then checked for size, SHA-256,
strict structural validity, and frame count before being published atomically.
If anything fails or you press Ctrl+C, no output is published and only the
temporary file created by that run is removed. The command prints the output
size and SHA-256 when it finishes.

Frame bytes are copied exactly. One narrow case adds bytes: if the source's
last frame has no final line terminator and you extract it *before* other
frames, a single line terminator (matching that frame's line-ending style) is
inserted after it so the next frame header starts on its own line. The command
reports how many separator bytes were inserted.

## Benchmark

Measure index build, index reuse and extraction. Benchmarks only read your
files; all indexes and outputs go to a temporary folder that is deleted
afterwards, and your own index files are never touched. The report lists file
sizes, SHA-256 hashes, repeated timings, throughput, and peak Python memory.

You must say whether the data is real or synthetic, so a report can never be
mislabelled:

```powershell
# Your own data (read-only); label it honestly
python -m oxdna_splitter benchmark --topology "moon.top" --trajectory "slice.dat" --data-kind research --report "bench_research.json"

# Generated test data (clearly marked SYNTHETIC in the report)
python -m oxdna_splitter benchmark --generate-synthetic 14894 25 --report "bench_synthetic.json"
```

Options: `--frames` (default: the first half of the frames), `--repeats`
(1-50, default 3), `--work-dir` (where temporary files go; use a drive with
enough free space), `--report` (also save JSON; refuses an existing file unless
`--overwrite`). Notes on interpreting results: timings are wall-clock and
include operating-system file caching; memory is Python-allocated memory
measured by `tracemalloc` (it excludes memory-mapped index pages and the OS
cache); results describe one computer and one dataset. Extraction speed
includes strict verification of the output, so it is not raw disk-copy speed.

## Running the tests

```powershell
$env:PYTHONPATH = "src"
py -m unittest discover -s tests
```

All fixtures are synthetic and created in temporary folders; your research
files are never used or modified by the test suite. The safety tests cover
corrupt and truncated indexes (every single-byte change and every truncation),
stale and moved files, interrupted index builds and extractions, publication
failures, invalid and empty inputs, CRLF and 15-field files, thousands of frames,
read-only sources, and bounded memory.

If a command reports that the index is stale or damaged, rebuild it with
`python -m oxdna_splitter index ... --rebuild-index`. An index is tied to the
exact location and contents of the topology and trajectory; if you move or edit
either file, build a new index.
