"""Read trajectory records while preserving their exact bytes and file offsets.

Trajectory file
        ↓
Read one bounded binary record
        ↓
Decode it for validation
        ↓
Keep its original bytes and start/end offsets
        ↓
Yield the record to the caller
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from .validation import _decode_record, _read_bounded_line


@dataclass(frozen=True)
class BinaryRecord:
    """One trajectory record with decoded text, original bytes, and exact offsets."""

    line_number: int
    start_offset: int
    end_offset: int
    raw: bytes
    text: str
    newline_style: str


def iter_binary_records(path: str | Path) -> Iterator[BinaryRecord]:
    """Yield bounded binary records with exact offsets and original bytes."""
    source = Path(path)
    offset = 0
    line_number = 0
    with source.open("rb") as handle:
        while True:
            line_number += 1
            raw = _read_bounded_line(handle, source, line_number, offset)
            if raw is None:
                return
            text, newline_style = _decode_record(raw, source, line_number, offset)
            end = offset + len(raw)
            yield BinaryRecord(line_number, offset, end, raw, text, newline_style)
            offset = end
