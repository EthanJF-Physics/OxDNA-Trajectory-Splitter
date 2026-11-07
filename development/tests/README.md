# Tests

Synthetic fixtures are created in temporary directories and are not real research data.
The supplied reference `.top` and `.dat` files stay outside this repository and are read-only.
Run with: `python -m unittest discover -s development/tests -v`
If a `src` layout import fails, set `PYTHONPATH=src` or install with `pip install -e .`.
