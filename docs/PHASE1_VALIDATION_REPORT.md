# Phase 1 Validation Report

**Project:** OxDNA Trajectory Splitter  
**Version:** 8.0.0  
**Phase:** Strict topology and trajectory validation  
**Validation mode:** Read-only

## Reference files

| Input | Size (bytes) | SHA-256 |
|---|---:|---|
| `moon(2).top` | 233,783 | `de54eda94f9057e9988083f163f4f3d9b77b2499cb17a985e8b1e8094e572175` |
| `slice(2).dat` | 23,090,647 | `0d86699f0a4566b0d7c957a5e5764fe58bd6dcf800b84d4566aecc817269c61c` |

## Observed structure

- Topology declares 14,894 nucleotides and contains exactly 14,894 records.
- The topology header declares 235 strands.
- Trajectory contains 25 complete frames.
- Each frame contains 3 headers (`t`, `b`, `E`) followed by 14,894 nucleotide records.
- Nucleotide records contain 9 numeric fields.
- Line endings are LF.
- The trajectory ends with a newline.
- No malformed records were detected by the Phase 1 validator.

## Automated tests

The synthetic unit-test suite covers:
- Valid minimal topology/trajectory pair.
- 15-field nucleotide records.
- CRLF and mixed line endings.
- Complete final frame without a final newline.
- Invalid numeric values including NaN.
- Incomplete frames.
- Topology count mismatch and malformed topology header.
- Blank records and wrong frame-header order.
- Inconsistent 9/15-field formats.
- Oversized records.

Synthetic fixtures are temporary test files, not research data.

## Result

The Phase 1 validator passed the supplied reference files. The reference files
were opened read-only. SHA-256 fingerprints were measured before and after the
validation run and matched the values above.

This report records only the checks actually run in this development session.
It does not claim Windows/Ubuntu cross-platform verification, 15-field support
against an independent real dataset, scientific correctness, or implementation
of indexing/extraction.
