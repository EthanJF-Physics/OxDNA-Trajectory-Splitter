"""Basic checks for the initial project scaffold."""

import unittest

import oxdna_splitter
from oxdna_splitter.cli import build_argument_parser


class ProjectScaffoldTests(unittest.TestCase):
    def test_package_version(self):
        self.assertEqual(oxdna_splitter.__version__, "8.2.0")

    def test_cli_parser_builds(self):
        parser = build_argument_parser()
        self.assertEqual(parser.prog, "oxdna-splitter")


if __name__ == "__main__":
    unittest.main()
