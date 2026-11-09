# Benchmark material

These files are retained development evidence, not scientific simulation data. The JSON reports were generated from synthetic trajectories and describe software performance only.

## Recorded environment

The retained JSON reports record their own environment and creation time. The current set was produced on Windows 11 (`Windows-11-10.0.26200-SP0`), CPython 3.15.2, AMD64, with 16 logical CPUs reported by Python. CPU model, storage device/model, filesystem, and other hardware details were not recorded, so results should not be treated as hardware-independent performance guarantees.

The reports are dated 2026-11-06 and 2026-11-07. Each JSON file contains the exact timestamp, source/output sizes, selected frames, hashes, timing summaries, and memory-measurement notes for that run.

## Files

- `stress-test-10mb.json`, `stress-test-50mb.json`, `stress-test-100mb.json`, `stress-test-1gb.json`, `stress-test-2gb.json`, `stress-test-4gb.json` — retained Windows scaling runs using synthetic trajectories of increasing size.
- `progress-test-1gb.json` — a later 1 GB-class synthetic run retained while checking progress/timing behavior.
- `oxdna-index-build-scaling-clean.png` — retained scaling figure. Treat the JSON reports as the primary evidence because they preserve the run metadata and measured values.

## What the timings mean

`index_build` scans and validates the trajectory while constructing frame offsets. `index_reuse` is not a constant-time lookup: opening an existing index verifies the recorded topology and trajectory SHA-256 hashes. The benchmark's `extraction` timing includes opening/verifying the index, copying the selected frame ranges, and validating/verifying the produced output.

Therefore, selecting only a few frames does **not** make the complete extraction command independent of source trajectory size. Source verification intentionally adds work proportional to the source data read. The actual frame-copying work depends on the selected byte ranges.

Timings are wall-clock measurements and can be affected by operating-system caching, storage performance, background activity, and machine differences. The reports use one repeat unless the individual JSON says otherwise.

## Memory measurements

Where present, peak-memory values come from `tracemalloc`. They measure Python-managed allocations only; they do not include memory-mapped index pages or the operating-system file cache.

## Scope and unresolved questions

These retained reports document Windows behavior on one recorded software environment. They are not a cross-platform performance guarantee. Linux functionality is covered by the automated test workflow and has also been tested separately, but equivalent retained Linux scaling JSON is not present in this directory. macOS performance has not been established here.

The Windows results should be interpreted as empirical measurements rather than a universal throughput claim. Additional controlled runs on other storage hardware and operating systems would be needed to separate implementation scaling from machine/filesystem effects.
