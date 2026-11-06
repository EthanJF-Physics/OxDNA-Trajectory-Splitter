# Tests

Synthetic fixtures are created in temporary directories and are not real research data.
The supplied reference `.top` and `.dat` files stay outside this repository and are read-only.
Run with: `python -m unittest discover -s tests -v`
If a `src` layout import fails, set `PYTHONPATH=src` or install with `pip install -e .`.

The Phase 5 report records the 112-test safety campaign and distinguishes
Windows-reported results from Linux sandbox results. The current Phase 6
release-candidate build reruns the complete suite in its Linux environment.
