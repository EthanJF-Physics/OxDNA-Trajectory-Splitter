"""Rules for the nucleotide-record fast path.

The fast path may only ever say "certainly valid under v8.1". Anything it cannot
prove must be declined (return False) so the unchanged v8.1 slow path decides,
including producing the exact v8.1 error. These tests check:

* the documented eligibility table,
* soundness: fast-accept implies v8.1-accept (directed corpus + 250k random inputs),
* the finiteness argument: every fast-eligible token is finite under float(),
* realistic exponent-form oxDNA records are really eligible (not just synthetic decimals),
* the production scanner actually takes the fast path (so the speedup is real).

Fixtures are synthetic and are not research data.
"""
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest import mock

from oxdna_splitter import indexing, validation
from oxdna_splitter.validation import (
    FAST_RECORD_MATCHERS,
    ValidationError,
    fast_record_accepts,
)

import _reference_v81 as v81
import test_scan_equivalence as eq

G9, G15 = eq.G9, eq.G15


def v81_record_accepts(raw: bytes, field_count: int) -> bool:
    """Oracle: would frozen v8.1 accept this nucleotide record given a known field count?"""
    try:
        text, _ = v81._decode_record(raw, None, 1, 0)
        fields = v81._tokens(text, None, 1, 0)
        if len(fields) != field_count:
            return False
        for token in fields:
            v81._parse_finite_number(token, path=None, line_number=1, offset=0)
        return True
    except ValidationError:
        return False


class EligibilityTableTests(unittest.TestCase):
    ACCEPT9 = [
        G9, G9 + b"\n", G9 + b"\r\n",
        b"1 1 1 1 1 1 1 1 1\n", b"1\t1\t1\t1\t1\t1\t1\t1\t1\n", b"1  \t 1 1 1 1 1 1 1 1\n",
        b"-3.14159 2.71828 -1.41421 0.5 -0.5 1e-05 -4.51257e-05 2.36223e-17 -1e-06\n",
        b"+1.0e+00 -1.0E-00 .5e-3 1.e5 0.000000e+00 1e-05 -0 0 1\r\n",
        b"1e+15 9.99999999999999e+14 1e99 1e-99 00 007 1. .5 -.5\n",
        b"9" * 30 + b" " + b"9" * 30 + b"." + b"9" * 30 + b" 1 1 1 1 1 1 1\n",
        b"9" * 30 + b"." + b"9" * 30 + b"e+99 1 1 1 1 1 1 1 1\n",
    ]
    DECLINE9 = [
        b" " + G9 + b"\n", G9 + b" \n", G9 + b"\t\n", b"\t" + G9, G9 + b" ",
        b"1 1 1 1 1 1 1 1 1e+007\n", b"1 1 1 1 1 1 1 1 1e-007\n", b"1 1 1 1 1 1 1 1 1e100\n",
        b"1 1 1 1 1 1 1 1 " + b"9" * 31 + b"\n",
        b"1 1 1 1 1 1 1 1 1." + b"9" * 31 + b"\n",
        b"1 1 1 1 1 1 1 1 ." + b"9" * 31 + b"\n",
        b"1 1 1 1 1 1 1 1 nan\n", b"1 1 1 1 1 1 1 1 inf\n", b"1 1 1 1 1 1 1 1 1e999\n",
        b"1 1 1 1 1 1 1 1 1e\n", b"1 1 1 1 1 1 1 1 .\n", b"1 1 1 1 1 1 1 1 1.2.3\n",
        b"1 1 1 1 1 1 1 1\n", b"1 1 1 1 1 1 1 1 1 1\n", G15 + b"\n", b"\n", b"",
        b"\x0b".join([b"1"] * 9), b"\x1c".join([b"1"] * 9), b"\xa0".join([b"1"] * 9),
        G9 + b"\xff\n", b"1 1 1 1 1 1 1 1 1\r\r\n", b"1 1 1 1 1 1 1 1 1\r", G9 + b"\n\n",
        b"1 1 1 1 1 1 1 1 1\n1 1 1 1 1 1 1 1 1\n", b"1\x001 1 1 1 1 1 1 1\n",
    ]

    def test_nine_field_table(self):
        for raw in self.ACCEPT9:
            self.assertTrue(fast_record_accepts(raw, 9), raw)
            self.assertTrue(v81_record_accepts(raw, 9), f"table error, v8.1 rejects {raw!r}")
        for raw in self.DECLINE9:
            self.assertFalse(fast_record_accepts(raw, 9), raw)

    def test_fifteen_field_table(self):
        accept = [G15, G15 + b"\n", G15 + b"\r\n", b" ".join([b"-4.51257e-05"] * 15) + b"\n"]
        decline = [G9 + b"\n", b" ".join([b"1"] * 14), b" ".join([b"1"] * 16), b" " + G15,
                   b" ".join([b"1e+007"] * 15)]
        for raw in accept:
            self.assertTrue(fast_record_accepts(raw, 15), raw)
            self.assertTrue(v81_record_accepts(raw, 15))
        for raw in decline:
            self.assertFalse(fast_record_accepts(raw, 15), raw)

    def test_only_supported_field_counts_have_a_fast_matcher(self):
        self.assertEqual(sorted(FAST_RECORD_MATCHERS), [9, 15])
        for count in (0, 1, 8, 10, 12, 14, 16, None):
            self.assertFalse(fast_record_accepts(b" ".join([b"1"] * 9), count), count)
        self.assertIs(type(fast_record_accepts(G9, 9)), bool)
        self.assertIs(type(fast_record_accepts(b"garbage", 9)), bool)


class SoundnessTests(unittest.TestCase):
    """fast_record_accepts(raw, n) must imply v8.1 accepts raw as an n-field record."""

    def test_directed_corpus_soundness(self):
        checked = accepted = 0
        for body in eq._corpus():
            for ending in (b"\n", b"\r\n", b""):
                raw = body + ending
                if len(raw) > validation.MAX_RECORD_BYTES or b"\n" in raw[:-1]:
                    continue                          # reader never hands such a record over
                for count in (9, 15):
                    checked += 1
                    if fast_record_accepts(raw, count):
                        accepted += 1
                        self.assertTrue(v81_record_accepts(raw, count), raw[:120])
        self.assertGreater(checked, 2000)
        self.assertGreater(accepted, 300)

    def test_random_inputs_soundness(self):
        rng = random.Random(424242)
        alphabet = [b"0", b"1", b"5", b"9", b".", b"-", b"+", b"e", b"E", b" ", b"\t", b"\r",
                    b"\n", b"a", b"\x00", b"\xff", b"\x1c", b"nan", b"inf", b"1e999", b"0.5",
                    b"e+", b"e-", b"..", b"--", b"1e5", b"e99", b"e100"]
        seeds = [G9, G15] + eq._realistic_lines(20, seed=9)
        accepted = 0
        for i in range(250_000):
            if i % 2:
                base = bytearray(rng.choice(seeds) + rng.choice((b"\n", b"\r\n", b"")))
                for _ in range(rng.randint(1, 3)):
                    pos = rng.randrange(len(base) + 1)
                    if rng.random() < 0.5 and base:
                        base[pos % len(base):pos % len(base) + 1] = rng.choice(alphabet)
                    else:
                        base[pos:pos] = rng.choice(alphabet)
                raw = bytes(base)
            else:
                raw = b"".join(rng.choice(alphabet) for _ in range(rng.randint(1, 45)))
            for count in (9, 15):
                if fast_record_accepts(raw, count):
                    accepted += 1
                    self.assertTrue(v81_record_accepts(raw, count), raw)
        self.assertGreater(accepted, 5000)


class FinitenessBoundTests(unittest.TestCase):
    """Why every fast-eligible token is finite under v8.1 semantics.

    A fast token is  [+-]? (D{1,I}(\\.D{0,F})? | \\.D{1,F}) ([eE][+-]?D{1,E})?  with
    I = _FAST_MAX_INT_DIGITS, F = _FAST_MAX_FRAC_DIGITS, E = _FAST_MAX_EXP_DIGITS.
    Its mantissa is < 10**I (integer part has at most I digits and the fraction adds
    less than 1), its decimal exponent is at most 10**E - 1, so |value| < 10**(I + 10**E - 1).
    float() overflows only above ~1.797e308, i.e. 10**308.25. Underflow with a
    negative exponent yields 0.0 or a subnormal, both finite. float() never raises on
    text the numeric grammar accepts. The tests tie the code's constants to that inequality.
    """

    def test_constants_imply_finite(self):
        import sys as _sys
        I, E = validation._FAST_MAX_INT_DIGITS, validation._FAST_MAX_EXP_DIGITS
        largest_exponent = 10 ** E - 1
        # exact integer arithmetic: 10**(I + largest_exponent) must be below DBL_MAX
        bound = 10 ** (I + largest_exponent)
        self.assertLess(bound, int(_sys.float_info.max))
        self.assertLess(I + largest_exponent, 300)            # comfortable safety margin

    def test_extreme_eligible_tokens_are_finite_under_v81(self):
        I, F = validation._FAST_MAX_INT_DIGITS, validation._FAST_MAX_FRAC_DIGITS
        nines_i, nines_f = b"9" * I, b"9" * F
        extremes = [
            nines_i + b"." + nines_f + b"e+99", b"-" + nines_i + b"." + nines_f + b"E+99",
            nines_i + b"e99", nines_i + b"." + b"e99", b"." + nines_f + b"e99",
            nines_i + b"." + nines_f + b"e-99", b"0." + b"0" * (F - 1) + b"1e-99",
            b"1e-99", b"0e0", b"1e0", b"-0.0e+00",
        ]
        for token in extremes:
            row = b" ".join([token] * 9)
            self.assertTrue(fast_record_accepts(row, 9), token)
            for field in row.split():
                value = v81._parse_finite_number(field.decode("ascii"), path=None, line_number=1, offset=0)
                self.assertTrue(abs(value) < float("inf"))

    def test_random_limit_tokens_are_finite(self):
        rng = random.Random(77)
        I, F = validation._FAST_MAX_INT_DIGITS, validation._FAST_MAX_FRAC_DIGITS
        for _ in range(30_000):
            sign = rng.choice((b"", b"+", b"-"))
            if rng.random() < 0.15:
                mant = b"." + bytes(rng.choice(b"0123456789") for _ in range(rng.randint(1, F)))
            else:
                mant = bytes(rng.choice(b"0123456789") for _ in range(rng.randint(1, I)))
                if rng.random() < 0.6:
                    mant += b"." + bytes(rng.choice(b"0123456789") for _ in range(rng.randint(0, F)))
            exp = b""
            if rng.random() < 0.7:
                exp = rng.choice(b"eE") .to_bytes(1, "big") + rng.choice((b"", b"+", b"-")) + \
                    bytes(rng.choice(b"0123456789") for _ in range(rng.randint(1, 2)))
            token = sign + mant + exp
            row = b" ".join([token] * 9)
            self.assertTrue(fast_record_accepts(row, 9), token)
            self.assertTrue(v81_record_accepts(row, 9), token)


class RealisticExponentFormTests(unittest.TestCase):
    """Do not optimize only the synthetic benchmark: oxDNA-style exponent forms must qualify."""

    def test_realistic_g15_records_are_fast_eligible(self):
        lines = eq._realistic_lines(300, seed=31)
        exp_lines = [ln for ln in lines if b"e" in ln]
        self.assertGreater(len(exp_lines), 100)
        for ln in lines:
            n = len(ln.split())
            if n in (9, 15):
                for ending in (b"\n", b"\r\n", b""):
                    self.assertTrue(fast_record_accepts(ln + ending, n), ln)
                    self.assertTrue(v81_record_accepts(ln + ending, n))

    def test_known_fallback_forms_are_declined_but_still_accepted_by_v81(self):
        for raw in (b"1 1 1 1 1 1 1 1 1e+007\n", b" 1 1 1 1 1 1 1 1 1\n", b"1 1 1 1 1 1 1 1 1 \n"):
            self.assertFalse(fast_record_accepts(raw, 9))
            self.assertTrue(v81_record_accepts(raw, 9))


class EngagementTests(unittest.TestCase):
    """The production scanner must really use the fast path (else any speedup claim is hollow)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "e.dat"

    def tearDown(self):
        self.temp.cleanup()

    def _decode_calls(self, data: bytes, n: int) -> int:
        self.path.write_bytes(data)
        calls = []
        real = indexing._decode_record
        def counting(*args, **kwargs):
            calls.append(1)
            return real(*args, **kwargs)
        with mock.patch.object(indexing, "_decode_record", counting), tempfile.TemporaryFile() as sp:
            indexing._scan_trajectory(self.path, n, sp)
        return len(calls)

    def test_decimal_and_exponent_data_take_the_fast_path(self):
        frames, n = 4, 50
        for width in (9, 15):
            records = [ln for ln in eq._realistic_lines(60, seed=1) if len(ln.split()) == width][:n]
            data = (eq.HEADER + b"\n".join(records) + b"\n") * frames
            # 3 header lines per frame + only the FIRST nucleotide record of the file uses the slow path
            self.assertEqual(self._decode_calls(data, n), 3 * frames + 1, width)

    def test_ineligible_records_fall_back_to_the_slow_path(self):
        records = [b" " + G9] * 20               # leading blank: valid under v8.1, never fast
        data = eq.HEADER + b"\n".join(records) + b"\n"
        self.assertEqual(self._decode_calls(data, 20), 3 + 20)


if __name__ == "__main__":
    unittest.main()
