"""Adversarial equivalence tests: production _scan_trajectory vs frozen v8.1.

For every input the production scanner must produce exactly what v8.1 produced:
the same result tuple and offset spool on success, or the same ValidationError
(code AND full message, which embeds file, frame, line, byte offset, expected and
actual) on failure. Fixtures are synthetic and are not research data.

Each corpus line is placed in several file positions so the optimized scanner is
exercised both before the field count is known (slow path) and after it is known
(fast path eligible).
"""
from pathlib import Path
import random
import tempfile
import unittest

from oxdna_splitter.indexing import _scan_trajectory
from oxdna_splitter.validation import ValidationError

import _reference_v81 as v81

HEADER = b"t = 0\nb = 10 10 10\nE = -1 0 1\n"
G9 = b"0 0 0 1 0 0 0 1 0"
G15 = b"0 0 0 1 0 0 0 1 0 0 0 0 0 0 0"
ENDINGS_MIDDLE = (b"\n", b"\r\n")
ENDINGS_LAST = (b"\n", b"\r\n", b"")


def _outcome(scan, path: Path, nucleotides: int):
    with tempfile.TemporaryFile() as spool:
        try:
            result = scan(path, nucleotides, spool)
        except ValidationError as exc:
            return ("ValidationError", exc.code, str(exc))
        except Exception as exc:  # any other exception type must also match
            return ("Exception", type(exc).__name__, str(exc))
        spool.seek(0)
        return ("ok", result, spool.read())


def _scenarios(body: bytes):
    """Yield (name, file_bytes, nucleotides_per_frame) placing `body` in several spots."""
    for e in ENDINGS_MIDDLE:
        mid = body + e
        yield "only-record", HEADER + mid, 1
        yield "first-of-3", HEADER + mid + G9 + b"\n" + G9 + b"\n", 3
        yield "middle-of-3", HEADER + G9 + b"\n" + mid + G9 + b"\n", 3
        yield "middle-of-3-ctx15", HEADER + G15 + b"\n" + mid + G15 + b"\n", 3
    for last in ENDINGS_LAST:
        end = body + last
        frame1 = HEADER + (G9 + b"\n") * 3
        yield "last-in-frame2", frame1 + HEADER + G9 + b"\n" + G9 + b"\n" + end, 3
        yield "last-ctx15", HEADER + G15 + b"\n" + G15 + b"\n" + end, 3


def _numbered(tokens, position):
    out = []
    for token in tokens:
        fields = [b"1"] * 9
        fields[position] = token
        out.append(b" ".join(fields))
    return out


# ---------------------------------------------------------------- corpora
VALID_TOKENS = [
    b"0", b"1", b"-1", b"+1", b"007", b"-0", b"1.", b"1.0", b".5", b"-.5", b"+.5",
    b"1e5", b"1E5", b"1e+5", b"1e-5", b"1E-05", b"1.5e+10", b"-1.234567890123456e-02",
    b".5e-3", b"1.e5", b"0e0", b"00e00", b"1e99", b"1e100", b"1e-99", b"1e-999",
    b"1e308", b"1.7976931348623157e308", b"9" * 30, b"9" * 31, b"9" * 308,
    b"1" + b"0" * 307, b"0." + b"0" * 50, b"9" * 30 + b"." + b"9" * 30 + b"e+99",
    b"9" * 30 + b"." + b"9" * 31, b"1e+007", b"1e-007", b"1E+15", b"9.99999999999999e+14",
]
INVALID_SYNTAX_TOKENS = [
    b"e5", b"1e", b"1e+", b"1e-", b"1e5.5", b"1ee5", b"1e+-5", b"--1", b"+-1", b"-+1",
    b"1.2.3", b"..5", b".", b"+.", b"-", b"+", b"1_000", b"0x10", b"1,5", b"1e5e5",
    b"1f", b"1d5", b"1e 5", b"1 e5", "１".encode("utf-8"), "١٢٣".encode("utf-8"),
    "1·5".encode("utf-8"), b"\xff", b"1\x00", b"\x001", b"1\xff", b"1e\xff",
]
NONFINITE_TOKENS = [
    b"nan", b"NaN", b"NAN", b"-nan", b"+nan", b"inf", b"Inf", b"INF", b"-inf", b"+inf",
    b"infinity", b"-Infinity", b"nan(1)", b"1e999", b"-1e999", b"+1e999", b"1e309",
    b"1.8e308", b"9" * 309, b"9" * 400, b"9" * 4000, b"1" + b"0" * 308,
    b"1e1000000", b"0e999", b"1e+0099", b"1E00999",
]
WHITESPACE_LINES = [
    b"\t".join([b"1"] * 9), b"  ".join([b"1"] * 9), b" \t ".join([b"1"] * 9),
    b"\x0b".join([b"1"] * 9), b"\x0c".join([b"1"] * 9),
    b"\x1c".join([b"1"] * 9), b"\x1d".join([b"1"] * 9), b"\x1e".join([b"1"] * 9),
    b"\x1f".join([b"1"] * 9), b"\xa0".join([b"1"] * 9), b"\xc2\xa0".join([b"1"] * 9),
    b"\x00".join([b"1"] * 9),
    b" " + G9, G9 + b" ", b"\t" + G9, G9 + b"\t", b"  " + G9 + b"  ", G9 + b"\x0b",
    G9 + b"\x1c", b"\x0c" + G9, b"\xc2\xa0" + G9, G9 + b"\xc2\xa0", b"\x00" + G9,
]
FIELD_COUNT_LINES = [b" ".join([b"1"] * n) for n in (1, 2, 8, 9, 10, 14, 15, 16, 18, 30, 100)]
BLANK_LINES = [b"", b" ", b"\t", b"   ", b"\x0b", b"\x1c", b"\xa0", b"\xc2\xa0"]
LINE_ENDING_LINES = [
    G9 + b"\r", G9 + b"\r\r", G9 + b"\r\r\n"[:-1], b"1 1\r1 1 1 1 1 1 1", b"\r" + G9,
    G9 + b"\n", G9 + b"\n\n", G9 + b"\r\n", G9 + b"\n\r", G15 + b"\r",
    b"1 1 1 1 1 1 1 1 1\n1 1 1 1 1 1 1 1 1",
]
NON_ASCII_LINES = [
    G9 + b"\xff", b"\xff" + G9, b"\xc3\xa9 1 1 1 1 1 1 1 1", b"1 1 1 1 1 1 1 1 \xe2\x82\xac",
    b"1 1 1 1 1 1 1 1 1\x80", b"1 1 1 1 1 1 1 1 1\x00",
]


def _boundary_lines():
    """Bodies sized so that body + ending straddles the 4096-byte record limit."""
    out = []
    for body_len in range(4092, 4100):
        pad = body_len - len(G9)
        out.append(G9 + b" " * pad)                                   # trailing spaces
        out.append(b" " * pad + G9)                                   # leading spaces
        out.append(G9 + b"\t" * pad)                                  # trailing tabs
        head = b"1 1 1 1 1 1 1 1 "
        out.append(head + b"0." + b"0" * (body_len - len(head) - 2))  # one long finite token
        out.append(head + b"9" * (body_len - len(head)))              # one long overflowing token
        out.append(b"1" * body_len)                                   # a single huge field
    return out


def _realistic_lines(count_each=60, seed=11):
    """oxDNA-like records formatted the way C++ default stream precision (%.15g) writes them."""
    rng = random.Random(seed)

    def fmt(value):
        return format(value, ".15g").encode("ascii")

    def draw(scale):
        r = rng.random()
        if r < 0.05:
            return 0.0
        if r < 0.25:                      # tiny values -> exponent form
            return rng.uniform(-1, 1) * 10 ** rng.randint(-17, -5)
        if r < 0.28:                      # large values -> exponent form
            return rng.uniform(-1, 1) * 10 ** rng.randint(15, 20)
        return rng.uniform(-scale, scale)

    lines = []
    for _ in range(count_each):
        lines.append(b" ".join(fmt(draw(40)) for _ in range(9)))
        lines.append(b" ".join(fmt(draw(40)) for _ in range(15)))
    lines += [
        b"-3.14159 2.71828 -1.41421 0.5 -0.5 1e-05 -4.51257e-05 2.36223e-17 -1e-06",
        b"1.098631439412436 -0.2417938 5.82e-05 1 0 0 0 1 0 -1.2e-07 3.1e-06 0 0 0 -1e-17",
        b"+1.0e+00 -1.0E-00 .5e-3 1.e5 0.000000e+00 1e-05 -0 0 1 2 3 4 5 6 7",
    ]
    return lines


def _corpus():
    lines = []
    for position in (0, 4, 8):
        lines += _numbered(VALID_TOKENS + INVALID_SYNTAX_TOKENS + NONFINITE_TOKENS, position)
    lines += WHITESPACE_LINES + FIELD_COUNT_LINES + BLANK_LINES + LINE_ENDING_LINES
    lines += NON_ASCII_LINES + _boundary_lines() + _realistic_lines() + [G9, G15]
    return lines


class ScanEquivalenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temp.name) / "case.dat"

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def compare(self, data: bytes, nucleotides: int, label: str):
        self.path.write_bytes(data)
        expected = _outcome(v81.scan_trajectory_v81, self.path, nucleotides)
        actual = _outcome(_scan_trajectory, self.path, nucleotides)
        self.assertEqual(actual, expected, f"{label}: {data[:160]!r}")
        return expected

    def test_corpus_matches_v81_in_every_position(self):
        corpus = _corpus()
        self.assertGreater(len(corpus), 400)
        accepted = rejected = scans = 0
        for body in corpus:
            for name, data, n in _scenarios(body):
                outcome = self.compare(data, n, name)
                scans += 1
                accepted += outcome[0] == "ok"
                rejected += outcome[0] != "ok"
        # Sanity: the corpus must exercise both outcomes heavily, or it proves little.
        self.assertGreater(accepted, 500)
        self.assertGreater(rejected, 1500)
        self.assertGreater(scans, 3000)

    def test_normal_files_produce_identical_results_and_offsets(self):
        rng = random.Random(5)
        lines9 = _realistic_lines(80, seed=3)
        for width, ending in ((9, b"\n"), (9, b"\r\n"), (15, b"\n"), (15, b"\r\n")):
            records = [ln for ln in lines9 if len(ln.split()) == width][:50]
            body = b"".join(r + ending for r in records)
            for frames, tail in ((1, b""), (3, b""), (3, None)):
                data = (HEADER.replace(b"\n", ending) + body) * frames
                if tail is None:                       # last record without a newline
                    data = data[: -len(ending)]
                outcome = self.compare(data, len(records), f"normal-{width}-{ending!r}-{frames}")
                self.assertEqual(outcome[0], "ok")
        # mixed LF/CRLF within one file
        mixed = b""
        for i, rec in enumerate(r for r in lines9 if len(r.split()) == 9):
            mixed += rec + (b"\r\n" if i % 2 else b"\n")
        self.assertEqual(self.compare(HEADER + mixed, len(mixed.splitlines()), "mixed")[0], "ok")
        self.assertIsNotNone(rng)

    def test_error_location_is_identical_deep_inside_a_large_frame(self):
        base = [G9] * 200
        for bad_index in (0, 1, 2, 57, 198, 199):
            for bad in (b"1 1 1 1 1 1 1 1 nan", b"1 1 1 1 1 1 1 1 1e999", b"1 1 1 1 1 1 1 1",
                        b"1 1 1 1 1 1 1 1 1e", b" ", b"1 1 1 1 1 1 1 1 1\xff", b"1\t1 1 1 1 1 1 1 1\r\r"):
                records = list(base)
                records[bad_index] = bad
                data = HEADER + b"\n".join(records) + b"\n"
                data = data + HEADER + b"\n".join(base) + b"\n"
                outcome = self.compare(data, 200, f"deep-{bad_index}")
                self.assertNotEqual(outcome[0], "ok", f"{bad!r}")
                # and the same defect in the second frame
                data2 = HEADER + b"\n".join(base) + b"\n" + HEADER + b"\n".join(records) + b"\n"
                self.assertNotEqual(self.compare(data2, 200, f"deep2-{bad_index}")[0], "ok")

    def test_truncation_and_structure_errors_match(self):
        good = HEADER + (G9 + b"\n") * 3
        cases = [
            good[:-1], good[:-5], good + b"t = 1\n", good + b"t = 1\nb = 1 1 1\n",
            good + b"t = 1\nb = 1 1 1\nE = 1 1 1\n" + G9 + b"\n",
            b"", b"\n", HEADER, HEADER + G9 + b"\n", good + b"\n", good + G9 + b"\n",
            b"t = nan\nb = 1 1 1\nE = 1 1 1\n" + G9 + b"\n" * 1,
        ]
        for data in cases:
            self.compare(data, 3, "structure")

    def test_randomized_mutations_match_v81(self):
        rng = random.Random(20260507)
        alphabet = [b"0", b"1", b"9", b".", b"-", b"+", b"e", b"E", b" ", b"\t", b"\r", b"\n",
                    b"a", b"\x00", b"\xff", b"\x1c", b"\x0b", b"nan", b"inf", b"1e999", b"0.5",
                    b"e+", b"e-", b"..", b"--", b"1e5"]
        seeds = [G9, G15] + [ln for ln in _realistic_lines(10, seed=2)]
        for i in range(2500):
            records = []
            for _ in range(4):
                records.append(bytearray(rng.choice(seeds)))
            target = records[rng.randrange(4)]
            for _ in range(rng.randint(1, 3)):
                op = rng.random()
                pos = rng.randrange(len(target) + 1)
                if op < 0.5 and target:
                    target[pos % len(target):pos % len(target) + 1] = rng.choice(alphabet)
                elif op < 0.8:
                    target[pos:pos] = rng.choice(alphabet)
                elif target:
                    del target[pos % len(target)]
            ending = rng.choice((b"\n", b"\r\n"))
            data = HEADER + ending.join(bytes(r) for r in records)
            if rng.random() < 0.7:
                data += ending
            self.compare(data, 4, f"mutation-{i}")


if __name__ == "__main__":
    unittest.main()
