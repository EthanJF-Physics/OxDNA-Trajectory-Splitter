# OxDNA Trajectory Splitter

A Python tool for validating oxDNA trajectory files and extracting selected frames into new trajectory files.

**Version:** 8.1.0

## Features

- Validate topology and trajectory files before extraction.
- Extract consecutive or nonconsecutive frames.
- Build reusable frame indexes for large trajectories.
- Preserve the original topology and trajectory files.
- Verify extracted trajectories before completion.
- Show progress, elapsed time, and estimated time remaining for long-running CLI operations.

Validation checks file structure and compatibility. It does not determine scientific correctness or simulation quality.

## Requirements

- Python 3.10 or newer.
- No third-party runtime dependencies.

## Getting Started

### 1. Download

Download the project using **Code → Download ZIP** on GitHub and extract the ZIP to a convenient location.

### 2. Install Python

Install Python 3.10 or newer.

On Windows, enable **Add Python to PATH** during installation.

### 3. Install OxDNA Trajectory Splitter

Open PowerShell or a terminal inside the extracted project directory.

**Windows:**

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
```

**Linux / macOS:**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
```

### 4. Check the installation

**Windows:**

```powershell
.\.venv\Scripts\oxdna-splitter.exe --help
```

**Linux / macOS:**

```bash
.venv/bin/oxdna-splitter --help
```

The available commands are:

- `validate` — validate topology and trajectory files.
- `index` — build or verify a frame index.
- `extract` — extract selected frames into a new trajectory.
- `benchmark` — measure indexing and extraction performance.

## Validate

Before extraction, validate your topology and trajectory:

```powershell
.\.venv\Scripts\oxdna-splitter.exe validate `
  --topology "path\to\system.top" `
  --trajectory "path\to\trajectory.dat"
```

Use `--verbose` for additional information.

A successful validation reports `VALIDATION PASSED`. Long-running interactive operations show a progress bar with elapsed time and, when enough progress is known, an estimated time remaining. Progress output is automatically suppressed when output is redirected, and `--quiet` remains quiet.

## Extract Frames

To extract frames 1 through 10:

```powershell
.\.venv\Scripts\oxdna-splitter.exe extract `
  --topology "path\to\system.top" `
  --trajectory "path\to\trajectory.dat" `
  --frames "1-10" `
  --output "extracted.dat" `
  --build-index
```

Frame numbers are one-based and ranges are inclusive.

Multiple ranges and individual frames can be combined:

```text
1-3,10,15-18,25
```

Selected ranges must not overlap.

The original topology and trajectory are not modified.

Useful extraction options:

- `--build-index` — build or refresh the required index automatically.
- `--dry-run` — check the extraction without creating an output file.
- `--overwrite` — allow replacement of an existing output file.
- `--index PATH` — specify a custom index location.

After extraction, the program verifies the new trajectory and reports the output file, size, SHA-256 hash, and extracted frame count.

## Build an Index

Indexes allow frames in large trajectories to be located efficiently.

```powershell
.\.venv\Scripts\oxdna-splitter.exe index `
  --topology "path\to\system.top" `
  --trajectory "path\to\trajectory.dat"
```

By default, an index named `trajectory.dat.oxidx` is created beside the trajectory.

If the topology or trajectory is moved or changed, build a new index.
