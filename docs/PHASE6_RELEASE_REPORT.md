# Phase 6 — Documentation and release-candidate report

## Documentation review

The project documentation was reviewed against the current package layout,
CLI parser, packaging metadata, and recorded phase reports. Corrections include:

- Updated the Phase 5 Windows test result to 112 passing tests, based on the
  project owner's report from the Windows PC on 2026-11-06.
- Removed the obsolete statement that the Phase 5 Windows run was still
  outstanding.
- Clarified that Linux sandbox testing is not a formal Ubuntu LTS release test.
- Updated the README roadmap and project status through Phase 6.
- Corrected release guidance: the maintained deliverable is the installable
  Python package; no standalone script is currently included or required.
- Set package attribution to `Project owner`, reflecting the project owner's
  confirmation that they created the software; no personal name was invented.
- Removed the premature `Planning` development-status classifier.

## Package and CLI review

The package metadata declares:
- Distribution: `oxdna-trajectory-splitter`
- Version: `8.0.0`
- Python requirement: `>=3.10`
- Runtime dependencies: none
- Console command: `oxdna-splitter`
- Module invocation: `python -m oxdna_splitter`

The CLI exposes `validate`, `index`, `extract`, and `benchmark`.

## Verification performed for this Phase 6 build

- Linux sandbox, Python runtime used for this build: `python -m unittest
  discover -s tests -v` — **112 tests passed**.
- CLI smoke check: `python -m oxdna_splitter --help` — passed; all four
  subcommands were listed.
- Wheel and source distribution built successfully with setuptools on Linux,
  Python 3.13.5.
- Installed the rebuilt wheel into an isolated target directory and ran
  `python -m oxdna_splitter --help`; all four subcommands were present.
- Confirmed the source distribution includes the `docs/` reports and release
  guidance via `MANIFEST.in`.
- Release ZIP includes the cleaned source tree, wheel, source distribution,
  and SHA-256 manifest. See `SHA256SUMS.txt` in the release ZIP.

The Windows result is separate evidence supplied by the project owner:
Windows 11, Python 3.15.2 — **112 tests passed**. It was not rerun from this
Linux packaging environment.

## Platform and scientific scope

- Windows 11: 112-test result reported by the project owner.
- Linux: 112 tests passed in the current sandbox.
- Ubuntu LTS: not formally tested as a release target; support is not claimed.
- Validation is structural and does not establish scientific correctness,
  strand connectivity, nucleotide identity correctness, or simulation quality.
- Synthetic fixtures and benchmarks are not scientifically valid research data.

## Authorship and licensing status

The project owner confirms they created this software. Package metadata records
the author as `Project owner`; no personal name is supplied in the package.

No software license is included or selected, by project-owner decision. This
is not treated as a Phase 6 blocker. The absence of a license does not put the
software in the public domain or grant open-source reuse rights; default
copyright rules may still apply.

## Remaining decisions before broader distribution

1. Decide whether a standalone executable or script is needed in addition to
   the installable Python package.
2. Run a release build and smoke test on every platform that will be advertised
   as supported.
3. If reuse or redistribution by others is intended, decide whether permission
   or an explicit license should be provided.
