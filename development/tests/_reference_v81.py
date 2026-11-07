"""FROZEN copy of the v8.1.0 trajectory scanner and its validation helpers.

Generated mechanically from the v8.1.0 source (not hand-edited). It is the oracle
for development/tests/test_scan_equivalence.py and development/tests/test_fastpath_rules.py: whatever the
optimized production scanner does must match this module exactly. Do not
"improve" this file; it exists to preserve v8.1 behavior.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import re
import struct
from typing import BinaryIO

from oxdna_splitter.validation import ValidationError

MAX_RECORD_BYTES = 4096



_NUMERIC = re.compile(
    r"^[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][+-]?\d+)?$"
)


_OFFSET = struct.Struct("<Q")


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


def _write_all(handle: BinaryIO, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = handle.write(view)
        if written is None or written <= 0:
            raise OSError("Short write while creating index.")
        view = view[written:]


def _parse_header(record: str, key: str, count: int, path: Path, line: int, offset: int) -> list[float]:
    fields = _tokens(record, path, line, offset)
    if len(fields) != count + 2 or fields[0] != key or fields[1] != "=":
        raise ValidationError(
            "INVALID_FRAME_HEADER", f"Expected '{key}' followed by {count} numeric value(s).",
            path=path, line_number=line, byte_offset=offset,
            expected=f"{key} plus {count} values", actual=record[:120],
        )
    return [
        _parse_finite_number(v, path=path, line_number=line, offset=offset)
        for v in fields[2:]
    ]


def scan_trajectory_v81(path: Path, nucleotide_count: int, offset_spool: BinaryIO, *, progress_callback=None) -> tuple[int, int, str, int, str]:
    """Validate/hash a trajectory once while spooling offsets with bounded RAM."""
    digest = hashlib.sha256()
    offset_digest = hashlib.sha256()
    offset = 0
    line = 0
    frame = 0
    field_count: int | None = None
    total_size = path.stat().st_size
    with path.open("rb") as handle:
        while True:
            frame_start = offset
            line += 1
            raw = _read_bounded_line(handle, path, line, offset)
            if raw is None:
                break
            record_offset = offset
            text, _ = _decode_record(raw, path, line, record_offset)
            digest.update(raw)
            offset += len(raw)
            _parse_header(text, "t", 1, path, line, record_offset)
            for key in ("b", "E"):
                line += 1
                raw = _read_bounded_line(handle, path, line, offset)
                if raw is None:
                    raise ValidationError("TRUNCATED_FRAME", f"Missing {key} header.", path=path, line_number=line, byte_offset=offset, frame_number=frame + 1)
                text, _ = _decode_record(raw, path, line, offset)
                digest.update(raw)
                _parse_header(text, key, 3, path, line, offset)
                offset += len(raw)
            for _ in range(nucleotide_count):
                line += 1
                raw = _read_bounded_line(handle, path, line, offset)
                if raw is None:
                    raise ValidationError("TRUNCATED_FRAME", "Frame has too few nucleotide records.", path=path, line_number=line, byte_offset=offset, frame_number=frame + 1, expected=str(nucleotide_count))
                text, _ = _decode_record(raw, path, line, offset)
                digest.update(raw)
                fields = _tokens(text, path, line, offset)
                if len(fields) not in (9, 15) or (field_count is not None and len(fields) != field_count):
                    raise ValidationError("INVALID_NUCLEOTIDE_RECORD", "Nucleotide record must contain consistently 9 or 15 numeric fields.", path=path, line_number=line, byte_offset=offset, frame_number=frame + 1, expected="9 or 15 consistent fields", actual=f"{len(fields)} fields")
                field_count = len(fields)
                for token in fields:
                    _parse_finite_number(token, path=path, line_number=line, offset=offset, frame=frame + 1)
                offset += len(raw)
            packed = _OFFSET.pack(frame_start)
            _write_all(offset_spool, packed)
            offset_digest.update(packed)
            frame += 1
            if progress_callback is not None:
                progress_callback(offset, total_size)
    if frame == 0:
        raise ValidationError("EMPTY_TRAJECTORY", "Trajectory contains no frames.", path=path)
    packed_eof = _OFFSET.pack(offset)
    _write_all(offset_spool, packed_eof)
    offset_digest.update(packed_eof)
    return frame, field_count or 0, digest.hexdigest(), offset, offset_digest.hexdigest()
