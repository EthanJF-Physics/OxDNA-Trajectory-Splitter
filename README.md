# OxDNA Trajectory Splitter

A Python tool for validating oxDNA trajectory files and extracting selected frames into new trajectory files.

**Version:** 8.2.0

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

```powershell id="gv0mnb"
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
```

**Linux:**

```bash id="2qf0kh"
python3 -m venv .venv
.venv/bin/python -m pip install .
```

### 4. Check the installation

**Windows:**

```powershell id="68mslb"
.\.venv\Scripts\python.exe -m oxdna_splitter --help
```

**Linux:**

```bash id="7jbg8k"
.venv/bin/oxdna-splitter --help
```

The available commands are:

- `validate` — validate topology and trajectory files.
- `index` — build or verify a frame index.
- `extract` — extract selected frames into a new trajectory.
- `benchmark` — measure indexing and extraction performance.

## Validate

Before extraction, validate your topology and trajectory. (You do not have to, you can just do extraction)

**Windows:**

```powershell id="8fvltu"
.\.venv\Scripts\python.exe -m oxdna_splitter validate `
  --topology "path\to\system.top" `
  --trajectory "path\to\trajectory.dat"
```

**Linux:**

```bash id="mfrzct"
.venv/bin/oxdna-splitter validate \
  --topology "path/to/system.top" \
  --trajectory "path/to/trajectory.dat"
```

Use `--verbose` for additional information.

A successful validation reports `VALIDATION PASSED`. Long-running interactive operations show a progress bar with elapsed time and, when enough progress is known, an estimated time remaining. Progress output is automatically suppressed when output is redirected, and `--quiet` remains quiet.

## Extract Frames

To extract frames 1 through 10:

**Windows:**

```powershell id="njvijc"
.\.venv\Scripts\python.exe -m oxdna_splitter extract `
  --topology "path\to\system.top" `
  --trajectory "path\to\trajectory.dat" `
  --frames "1-10" `
  --output "extracted.dat" `
  --build-index
```

**Linux:**

```bash id="yuvy08"
.venv/bin/oxdna-splitter extract \
  --topology "path/to/system.top" \
  --trajectory "path/to/trajectory.dat" \
  --frames "1-10" \
  --output "extracted.dat" \
  --build-index
```

Frame numbers are one-based and ranges are inclusive.

Multiple ranges and individual frames can be combined:

```text id="zgjv5h"
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

**Performance note:** extraction prioritizes source integrity. Opening/reusing an index verifies the source topology and trajectory hashes before copying frames, so total extraction time can grow with source-file size even when only a small, fixed number of frames is selected. The frame-copying work itself depends on the selected byte ranges.

## Build an Index

Indexes allow frames in large trajectories to be located efficiently.

**Windows:**

```powershell id="i41ojd"
.\.venv\Scripts\python.exe -m oxdna_splitter index `
  --topology "path\to\system.top" `
  --trajectory "path\to\trajectory.dat"
```

**Linux:**

```bash id="9phzvp"
.venv/bin/oxdna-splitter index \
  --topology "path/to/system.top" \
  --trajectory "path/to/trajectory.dat"
```

By default, an index named `trajectory.dat.oxidx` is created beside the trajectory.

If the topology or trajectory is moved or changed, build a new index.

## Viewing Extracted Trajectories

The extracted trajectory can be opened and visualized using **oxView**:

[https://sulcgroup.github.io/oxdna-viewer/](https://sulcgroup.github.io/oxdna-viewer/)

For information about oxView and the oxDNA ecosystem, see:

- Poppleton et al., *Design, optimization and analysis of large DNA and RNA nanostructures through interactive visualization, editing and molecular simulation*, Nucleic Acids Research (2020):  
  [https://doi.org/10.1093/nar/gkaa417](https://doi.org/10.1093/nar/gkaa417)
- Bohlin et al., *Design and simulation of DNA, RNA and hybrid protein-nucleic acid nanostructures with oxView*, Nature Protocols (2022):  
  [https://doi.org/10.1038/s41596-022-00688-5](https://doi.org/10.1038/s41596-022-00688-5)
- Poppleton et al., *oxDNA: coarse-grained simulations of nucleic acids made simple*, Journal of Open Source Software (2023):  
  [https://doi.org/10.21105/joss.04693](https://doi.org/10.21105/joss.04693)
