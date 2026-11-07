"""Strict, read-only validation for the supported oxDNA topology/trajectory layout.

This module deliberately validates structure and finite numeric values. It does not
attempt to judge whether a simulation is scientifically correct.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re

MAX_RECORD_BYTES = 4096
_NUMERIC = re.compile(
    r"^[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][+-]?\d+)?$"
)

# ---------------------------------------------------------------------------
# Fast path for trajectory nucleotide records (used only by indexing).
#
# The fast path may only ever answer "this record is certainly valid under the
# strict rules above". It never rejects anything: a record it does not accept
# goes through the unchanged strict path, which decides and produces the exact
# error. To make "certainly valid" provable, the fast number grammar is a bounded
# subset of _NUMERIC:
#   - the same syntax as _NUMERIC (ASCII digits only; bytes patterns never match
#     non-ASCII), but with at most _FAST_MAX_INT_DIGITS integer digits,
#     _FAST_MAX_FRAC_DIGITS fraction digits and _FAST_MAX_EXP_DIGITS exponent digits;
#   - fields separated by spaces/tabs only, no leading/trailing blanks, and an
#     optional single LF or CRLF ending (no other carriage returns).
# Finiteness: the mantissa is < 10**_FAST_MAX_INT_DIGITS and the decimal exponent is
# at most 10**_FAST_MAX_EXP_DIGITS - 1, so |value| < 10**(30 + 99) = 10**129, far below
# the float64 maximum (~1.8e308). Negative exponents can only underflow to zero or a
# subnormal, which are finite. float() does not raise on text matching the grammar.
# development/tests/test_fastpath_rules.py ties these constants to that inequality.
_FAST_MAX_INT_DIGITS = 30
_FAST_MAX_FRAC_DIGITS = 30
_FAST_MAX_EXP_DIGITS = 2
_FAST_NUMBER = (
    rb"[+-]?(?:\d{1,%d}(?:\.\d{0,%d})?|\.\d{1,%d})(?:[eE][+-]?\d{1,%d})?"
    % (_FAST_MAX_INT_DIGITS, _FAST_MAX_FRAC_DIGITS, _FAST_MAX_FRAC_DIGITS, _FAST_MAX_EXP_DIGITS)
)


def _compile_fast_record(field_count: int):
    pattern = _FAST_NUMBER + rb"(?:[ \t]+" + _FAST_NUMBER + rb"){%d}" % (field_count - 1) + rb"(?:\r?\n)?"
    return re.compile(pattern).fullmatch


# field count -> bound fullmatch(raw_record_bytes); returns a match object or None
FAST_RECORD_MATCHERS = {count: _compile_fast_record(count) for count in (9, 15)}


def fast_record_accepts(raw: bytes, field_count: int | None) -> bool:
    """True only if `raw` is certainly a valid `field_count`-field nucleotide record."""
    matcher = FAST_RECORD_MATCHERS.get(field_count)
    return matcher is not None and matcher(raw) is not None


@dataclass(frozen=True)
class TopologyInfo:
    path: Path
    nucleotide_count: int
    strand_count: int | None
    size_bytes: int
    record_count: int


@dataclass(frozen=True)
class ValidationSummary:
    topology: TopologyInfo
    trajectory_path: Path
    trajectory_size_bytes: int
    frame_count: int
    nucleotide_count: int
    nucleotide_fields: int
    newline_styles: tuple[str, ...]
    first_frame_time: float
    last_frame_time: float


class ValidationError(Exception):
    """A validation failure with a stable machine-readable code and location."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: str | Path | None = None,
        line_number: int | None = None,
        byte_offset: int | None = None,
        frame_number: int | None = None,
        expected: str | None = None,
        actual: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.path = str(path) if path is not None else None
        self.line_number = line_number
        self.byte_offset = byte_offset
        self.frame_number = frame_number
        self.expected = expected
        self.actual = actual
        self.suggestion = suggestion
        details = [f"{code}: {message}"]
        if self.path is not None:
            details.append(f"file={self.path}")
        if frame_number is not None:
            details.append(f"frame={frame_number}")
        if line_number is not None:
            details.append(f"line={line_number}")
        if byte_offset is not None:
            details.append(f"byte_offset={byte_offset}")
        if expected is not None:
            details.append(f"expected={expected}")
        if actual is not None:
            details.append(f"actual={actual}")
        if suggestion is not None:
            details.append(f"suggestion={suggestion}")
        super().__init__(" | ".join(details))


def _read_bounded_line(handle, path: Path, line_number: int, offset: int) -> bytes | None:
    """Read at most MAX_RECORD_BYTES plus one sentinel byte."""
    raw = handle.readline(MAX_RECORD_BYTES + 1)
    if not raw:
        return None
    if len(raw) > MAX_RECORD_BYTES:
        raise ValidationError(
            "RECORD_TOO_LONG",
            f"Record exceeds the {MAX_RECORD_BYTES}-byte limit.",
            path=path,
            line_number=line_number,
            byte_offset=offset,
            expected=f"at most {MAX_RECORD_BYTES} bytes including newline",
            actual=f"at least {len(raw)} bytes",
            suggestion="Inspect the record; v8 does not accept oversized records.",
        )
    return raw


def _decode_record(raw: bytes, path: Path, line_number: int, offset: int) -> tuple[str, str]:
    """Decode an ASCII record and return (text_without_ending, newline_style)."""
    if raw.endswith(b"\r\n"):
        body, newline = raw[:-2], "CRLF"
    elif raw.endswith(b"\n"):
        body, newline = raw[:-1], "LF"
    else:
        body, newline = raw, "NONE"
    if b"\r" in body:
        raise ValidationError(
            "INVALID_NEWLINE",
            "Carriage return found inside a record.",
            path=path, line_number=line_number, byte_offset=offset,
            suggestion="Use LF or CRLF line endings.",
        )
    try:
        return body.decode("ascii"), newline
    except UnicodeDecodeError as exc:
        raise ValidationError(
            "NON_ASCII_RECORD",
            "Record contains bytes outside the supported ASCII numeric/text format.",
            path=path, line_number=line_number, byte_offset=offset,
            suggestion="Check for unexpected encoding or binary data.",
        ) from exc


def _tokens(text: str, path: Path, line_number: int, offset: int) -> list[str]:
    if not text.strip():
        raise ValidationError(
            "BLANK_RECORD", "Blank lines are not permitted in strict mode.",
            path=path, line_number=line_number, byte_offset=offset,
            suggestion="Remove the blank line only in a disposable copy, then validate again.",
        )
    return text.split()


def _parse_finite_number(
    token: str, *, path: Path, line_number: int, offset: int, frame: int | None = None
) -> float:
    if not _NUMERIC.fullmatch(token):
        raise ValidationError(
            "INVALID_NUMERIC_FIELD",
            "Field is not a supported numeric value.",
            path=path, line_number=line_number, byte_offset=offset, frame_number=frame,
            expected="integer, decimal, or scientific notation",
            actual=token[:80],
        )
    value = float(token)
    if not math.isfinite(value):
        raise ValidationError(
            "NONFINITE_NUMERIC_FIELD",
            "NaN and infinity are not permitted.",
            path=path, line_number=line_number, byte_offset=offset, frame_number=frame,
            actual=token[:80],
        )
    return value


def validate_topology(path: str | Path) -> TopologyInfo:
    """Validate the topology record count and basic four-field record structure."""
    source = Path(path)
    try:
        before = source.stat()
        handle = source.open("rb")
    except OSError as exc:
        raise ValidationError(
            "TOPOLOGY_READ_ERROR", f"Cannot open topology: {exc}", path=source
        ) from exc

    try:
        with handle:
            offset = 0
            line_number = 1
            first = _read_bounded_line(handle, source, line_number, offset)
            if first is None:
                raise ValidationError("EMPTY_TOPOLOGY", "Topology file is empty.", path=source)
            text, _ = _decode_record(first, source, line_number, offset)
            header = _tokens(text, source, line_number, offset)
            try:
                nucleotide_count = int(header[0])
            except (ValueError, IndexError) as exc:
                raise ValidationError(
                    "INVALID_TOPOLOGY_HEADER",
                    "The first topology header value must be a positive integer.",
                    path=source, line_number=1, byte_offset=0,
                    expected="positive integer nucleotide count",
                    actual=text[:120],
                ) from exc
            if nucleotide_count <= 0:
                raise ValidationError(
                    "INVALID_TOPOLOGY_HEADER",
                    "The nucleotide count must be positive.",
                    path=source, line_number=1, byte_offset=0,
                    expected="positive integer", actual=str(nucleotide_count),
                )
            if len(header) != 2:
                raise ValidationError(
                    "INVALID_TOPOLOGY_HEADER",
                    "The topology header must contain exactly two integer values.",
                    path=source, line_number=1, byte_offset=0,
                    expected="nucleotide_count strand_count",
                    actual=f"{len(header)} fields",
                )
            try:
                strand_count = int(header[1])
            except ValueError as exc:
                raise ValidationError(
                    "INVALID_TOPOLOGY_HEADER",
                    "The second topology header value must be an integer.",
                    path=source, line_number=1, byte_offset=0,
                    actual=header[1],
                ) from exc

            offset += len(first)
            record_count = 0
            while True:
                line_number += 1
                raw = _read_bounded_line(handle, source, line_number, offset)
                if raw is None:
                    break
                text, _ = _decode_record(raw, source, line_number, offset)
                fields = _tokens(text, source, line_number, offset)
                if len(fields) != 4:
                    raise ValidationError(
                        "INVALID_TOPOLOGY_RECORD",
                        "Topology nucleotide records must contain exactly four fields.",
                        path=source, line_number=line_number, byte_offset=offset,
                        expected="4 fields", actual=f"{len(fields)} fields",
                    )
                try:
                    int(fields[0])
                    int(fields[2])
                    int(fields[3])
                except ValueError as exc:
                    raise ValidationError(
                        "INVALID_TOPOLOGY_RECORD",
                        "Topology strand/neighbor fields must be integers.",
                        path=source, line_number=line_number, byte_offset=offset,
                        expected="integer fields 1, 3, and 4",
                        actual=text[:120],
                    ) from exc
                if not fields[1]:
                    raise ValidationError(
                        "INVALID_TOPOLOGY_RECORD", "Topology base field is empty.",
                        path=source, line_number=line_number, byte_offset=offset,
                    )
                record_count += 1
                offset += len(raw)

            if record_count != nucleotide_count:
                raise ValidationError(
                    "TOPOLOGY_COUNT_MISMATCH",
                    "The number of topology records does not match the declared nucleotide count.",
                    path=source, expected=str(nucleotide_count), actual=str(record_count),
                    suggestion="Check for missing or extra topology records.",
                )
        after = source.stat()
    except OSError as exc:
        raise ValidationError(
            "TOPOLOGY_READ_ERROR", f"Error while reading topology: {exc}", path=source
        ) from exc

    before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before_identity != after_identity:
        raise ValidationError(
            "SOURCE_CHANGED",
            "Topology metadata changed while it was being validated.",
            path=source,
            suggestion="Stop other processes that may be writing this file and retry.",
        )
    return TopologyInfo(
        path=source.resolve(), nucleotide_count=nucleotide_count,
        strand_count=strand_count, size_bytes=after.st_size, record_count=record_count,
    )


def _validate_header(
    text: str, expected_key: str, expected_count: int,
    path: Path, line_number: int, offset: int, frame_number: int
) -> list[float]:
    fields = _tokens(text, path, line_number, offset)
    if len(fields) != expected_count + 2 or fields[0] != expected_key or fields[1] != "=":
        raise ValidationError(
            "INVALID_FRAME_HEADER",
            f"Expected header '{expected_key} = ...' with {expected_count} value(s).",
            path=path, line_number=line_number, byte_offset=offset,
            frame_number=frame_number,
            expected=f"{expected_key} = {' '.join(['<number>'] * expected_count)}",
            actual=text[:160],
        )
    return [
        _parse_finite_number(
            token, path=path, line_number=line_number, offset=offset, frame=frame_number
        )
        for token in fields[2:]
    ]


def validate_trajectory(
    path: str | Path, nucleotide_count: int, *, progress_callback=None
) -> tuple[int, int, tuple[str, ...], float, float]:
    """Validate trajectory frames in bounded-memory binary streaming mode.

    Returns (frame_count, record_field_count, newline_styles, first_time, last_time).
    """
    source = Path(path)
    if nucleotide_count <= 0:
        raise ValueError("nucleotide_count must be positive")
    try:
        before = source.stat()
        handle = source.open("rb")
    except OSError as exc:
        raise ValidationError(
            "TRAJECTORY_READ_ERROR", f"Cannot open trajectory: {exc}", path=source
        ) from exc

    frame_count = 0
    field_count: int | None = None
    newline_styles: set[str] = set()
    first_time = last_time = 0.0
    line_number = 0
    offset = 0

    try:
        with handle:
            while True:
                # EOF is valid only between complete frames.
                line_number += 1
                frame_start = offset
                raw = _read_bounded_line(handle, source, line_number, offset)
                if raw is None:
                    break
                frame_number = frame_count + 1
                text, ending = _decode_record(raw, source, line_number, offset)
                newline_styles.add(ending)
                time_value = _validate_header(
                    text, "t", 1, source, line_number, offset, frame_number
                )[0]
                offset += len(raw)

                for key, count in (("b", 3), ("E", 3)):
                    line_number += 1
                    raw = _read_bounded_line(handle, source, line_number, offset)
                    if raw is None:
                        raise ValidationError(
                            "INCOMPLETE_FRAME",
                            f"Frame ended before its '{key}' header.",
                            path=source, line_number=line_number,
                            byte_offset=offset, frame_number=frame_number,
                            expected=f"'{key} = ...' header",
                            actual="end of file",
                        )
                    text, ending = _decode_record(raw, source, line_number, offset)
                    newline_styles.add(ending)
                    _validate_header(text, key, count, source, line_number, offset, frame_number)
                    offset += len(raw)

                for nucleotide_index in range(1, nucleotide_count + 1):
                    line_number += 1
                    raw = _read_bounded_line(handle, source, line_number, offset)
                    if raw is None:
                        raise ValidationError(
                            "INCOMPLETE_FRAME",
                            "Frame ended before all nucleotide records were read.",
                            path=source, line_number=line_number,
                            byte_offset=offset, frame_number=frame_number,
                            expected=f"{nucleotide_count} nucleotide records",
                            actual=f"only {nucleotide_index - 1} records",
                        )
                    text, ending = _decode_record(raw, source, line_number, offset)
                    newline_styles.add(ending)
                    fields = _tokens(text, source, line_number, offset)
                    if len(fields) not in (9, 15):
                        raise ValidationError(
                            "INVALID_NUCLEOTIDE_RECORD",
                            "Trajectory nucleotide records must contain 9 or 15 numeric fields.",
                            path=source, line_number=line_number, byte_offset=offset,
                            frame_number=frame_number,
                            expected="9 or 15 fields", actual=f"{len(fields)} fields",
                        )
                    if field_count is None:
                        field_count = len(fields)
                    elif len(fields) != field_count:
                        raise ValidationError(
                            "INCONSISTENT_RECORD_FORMAT",
                            "Nucleotide field count changed within the trajectory.",
                            path=source, line_number=line_number, byte_offset=offset,
                            frame_number=frame_number,
                            expected=f"{field_count} fields", actual=f"{len(fields)} fields",
                        )
                    for token in fields:
                        _parse_finite_number(
                            token, path=source, line_number=line_number,
                            offset=offset, frame=frame_number,
                        )
                    offset += len(raw)

                frame_count += 1
                if frame_count == 1:
                    first_time = time_value
                last_time = time_value
                if progress_callback is not None:
                    progress_callback(frame_count, offset, before.st_size)

        after = source.stat()
    except OSError as exc:
        raise ValidationError(
            "TRAJECTORY_READ_ERROR", f"Error while reading trajectory: {exc}", path=source
        ) from exc

    if frame_count == 0:
        raise ValidationError("EMPTY_TRAJECTORY", "Trajectory contains no frames.", path=source)
    before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before_identity != after_identity:
        raise ValidationError(
            "SOURCE_CHANGED",
            "Trajectory metadata changed while it was being validated.",
            path=source,
            suggestion="Stop other processes that may be writing this file and retry.",
        )
    styles = tuple(sorted(newline_styles))
    return frame_count, int(field_count or 0), styles, first_time, last_time


def validate_files(topology_path: str | Path, trajectory_path: str | Path, *, progress_callback=None) -> ValidationSummary:
    """Validate a topology and its corresponding trajectory without writing files."""
    topology = validate_topology(topology_path)
    trajectory = Path(trajectory_path)
    try:
        size = trajectory.stat().st_size
    except OSError as exc:
        raise ValidationError(
            "TRAJECTORY_READ_ERROR", f"Cannot stat trajectory: {exc}", path=trajectory
        ) from exc
    frames, fields, newlines, first_time, last_time = validate_trajectory(
        trajectory, topology.nucleotide_count, progress_callback=progress_callback
    )
    return ValidationSummary(
        topology=topology,
        trajectory_path=trajectory.resolve(),
        trajectory_size_bytes=size,
        frame_count=frames,
        nucleotide_count=topology.nucleotide_count,
        nucleotide_fields=fields,
        newline_styles=newlines,
        first_frame_time=first_time,
        last_frame_time=last_time,
    )
