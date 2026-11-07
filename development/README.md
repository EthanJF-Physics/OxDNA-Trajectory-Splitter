# Development material

This directory contains supporting material for development, verification, and performance analysis. It is not required for normal use of OxDNA Trajectory Splitter.

- `tests/` - automated test suite and reference implementation used for equivalence checks.
- `docs/` - architecture and implementation notes.
- `tools/` - development and comparison utilities.
- `benchmarks/` - retained benchmark reports and scaling-analysis figures.

From the repository root, run the test suite with:

```bash
python -m unittest discover -s development/tests -v
```
