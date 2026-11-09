"""Extract selected frames exactly into a new file, verifying before publication.

User's frame request
        ↓
Understand requested ranges
        ↓
Check output is safe
        ↓
Open + verify index
        ↓
Plan exactly what will be copied
        ↓
Copy source bytes → temporary file
        ↓
Verify temporary file
        ↓
Check sources didn't change
        ↓
Publish temporary file as final output
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile
from .indexing import (
    IndexReader,
    _fsync_directory,
    _hash_file,
    _stat_identity,
    _write_all,
    build_index,
    default_index_path,
    open_index,
)
from .validation import ValidationError, validate_trajectory

COPY_CHUNK_BYTES = 1024 * 1024
_TAIL_BYTES = 8192
_MAX_NUMBER_DIGITS = 18
_RANGE_TOKEN = re.compile(r"([0-9]+)(?:-([0-9]+))?", re.ASCII)


class ExtractionError(Exception):
    """Base class for extraction failures; carries a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class FrameRangeError(ExtractionError):
    """The requested frame range is malformed, overlapping, or out of bounds."""

    pass


class OutputPathError(ExtractionError):
    """The requested output path is unsafe or cannot be used."""

    pass


class ExtractionVerificationError(ExtractionError):
    """The temporary extracted trajectory failed a safety or integrity check."""

    pass


@dataclass(frozen=True)
class FrameRange:
    """Inclusive, one-based frame range."""
    start: int
    end: int

    @property
    def count(self) -> int:
        return self.end - self.start + 1


@dataclass(frozen=True)
class ExtractionPlan:
    """Describe the verified source byte ranges that an extraction will copy."""

    topology_path: Path
    trajectory_path: Path
    index_path: Path
    output_path: Path
    ranges: tuple[FrameRange, ...]
    frames_selected: int
    source_frame_count: int
    nucleotide_count: int
    nucleotide_fields: int
    expected_bytes: int
    separator: bytes
    separator_after_range: int | None
    output_exists: bool
    overwrite: bool


@dataclass(frozen=True)
class ExtractionResult:
    """Summarize a completed extraction and its verified output."""

    output_path: Path
    topology_path: Path
    trajectory_path: Path
    index_path: Path
    ranges: tuple[FrameRange, ...]
    frames_extracted: int
    source_frame_count: int
    nucleotide_count: int
    nucleotide_fields: int
    bytes_written: int
    sha256: str
    separator_bytes_inserted: int
    overwritten: bool


def parse_frame_ranges(spec: str, frame_count: int | None = None) -> tuple[FrameRange, ...]:
    """Parse e.g. ``"1-5,10,20-25"`` into inclusive one-based ranges.

    Requested order is preserved. Ranges must not overlap, even when listed out
    of order. If ``frame_count`` is given, every frame must exist.
    """
    if not isinstance(spec, str) or not spec.strip():
        raise FrameRangeError("INVALID_FRAME_RANGE", "No frame range was given.")
    ranges: list[FrameRange] = []
    for raw_token in spec.split(","):
        token = raw_token.strip()
        match = _RANGE_TOKEN.fullmatch(token)
        if not match:
            raise FrameRangeError(
                "INVALID_FRAME_RANGE",
                f"Cannot read {token!r}; use N or N-M with positive whole numbers, separated by commas.",
            )
        first, last = match.group(1), match.group(2)
        if len(first) > _MAX_NUMBER_DIGITS or (last is not None and len(last) > _MAX_NUMBER_DIGITS):
            raise FrameRangeError("INVALID_FRAME_RANGE", f"Frame number in {token!r} is unreasonably large.")
        start = int(first)
        end = int(last) if last is not None else start
        if start < 1:
            raise FrameRangeError("INVALID_FRAME_RANGE", f"Frame numbers start at 1; got {token!r}.")
        if end < start:
            raise FrameRangeError("INVALID_FRAME_RANGE", f"Range {token!r} ends before it starts.")
        if frame_count is not None and end > frame_count:
            raise FrameRangeError(
                "FRAME_OUT_OF_RANGE",
                f"Range {token!r} goes past the last frame; the trajectory has {frame_count} frame(s).",
            )
        ranges.append(FrameRange(start, end))
    ordered = sorted(ranges, key=lambda r: r.start)
    for before, after in zip(ordered, ordered[1:]):
        if after.start <= before.end:
            raise FrameRangeError(
                "OVERLAPPING_FRAME_RANGES",
                f"Ranges {before.start}-{before.end} and {after.start}-{after.end} overlap.",
            )
    return tuple(ranges)


def _same_file(a: Path, b: Path) -> bool:
    if os.path.normcase(str(a)) == os.path.normcase(str(b)):
        return True
    try:
        return a.exists() and b.exists() and os.path.samefile(a, b)
    except OSError:
        return False


def _check_output_path(
    output: Path, protected: tuple[tuple[str, Path], ...], overwrite: bool
) -> bool:
    """Refuse unsafe destinations. Returns True if the destination already exists."""
    for label, path in protected:
        if _same_file(output, path):
            raise OutputPathError(
                "OUTPUT_IS_PROTECTED_FILE", f"Output must not be the {label} file: {path}"
            )
    if output.is_dir():
        raise OutputPathError("OUTPUT_IS_DIRECTORY", f"Output path is a directory: {output}")
    if not output.parent.is_dir():
        raise OutputPathError(
            "OUTPUT_DIRECTORY_MISSING", f"Output directory does not exist: {output.parent}"
        )
    exists = output.exists()
    if exists and not overwrite:
        raise OutputPathError(
            "OUTPUT_EXISTS", f"Output already exists and was not changed: {output}. Use --overwrite to replace it."
        )
    if exists and not output.is_file():
        raise OutputPathError("OUTPUT_NOT_A_FILE", f"Refusing to replace a non-regular file: {output}")
    return exists


def _separator_after_final_frame(reader: IndexReader, trajectory: Path) -> bytes:
    """Terminator needed after the source's last frame, or b'' if it already has one."""
    start, end = reader.frame_range(reader.summary.frame_count)
    length = min(end - start, _TAIL_BYTES)
    with trajectory.open("rb") as handle:
        handle.seek(end - length)
        tail = handle.read(length)
    if len(tail) != length:
        raise ExtractionError("SOURCE_TRUNCATED", "Trajectory is shorter than its index records.")
    if tail.endswith(b"\n"):
        return b""
    newline_at = tail.rfind(b"\n")
    if newline_at > 0 and tail[newline_at - 1:newline_at] == b"\r":
        return b"\r\n"
    return b"\n"


def _build_plan(
    reader: IndexReader,
    topology: Path,
    trajectory: Path,
    index_path: Path,
    frames_spec: str,
    output: Path,
    overwrite: bool,
) -> ExtractionPlan:
    summary = reader.summary
    ranges = parse_frame_ranges(frames_spec, summary.frame_count)
    existed = _check_output_path(
        output,
        (("topology", topology), ("trajectory", trajectory), ("index", index_path)),
        overwrite,
    )
    payload = sum(reader.offset(r.end) - reader.offset(r.start - 1) for r in ranges)
    separator = b""
    separator_after: int | None = None
    for position, rng in enumerate(ranges):
        if rng.end == summary.frame_count and position != len(ranges) - 1:
            separator = _separator_after_final_frame(reader, trajectory)
            if separator:
                separator_after = position
    expected = payload + len(separator)
    free = shutil.disk_usage(output.parent).free
    if free < expected:
        raise ExtractionError(
            "INSUFFICIENT_DISK_SPACE",
            f"Need {expected:,} bytes in {output.parent} but only {free:,} are free. Nothing was written.",
        )
    return ExtractionPlan(
        topology, trajectory, index_path, output, ranges,
        sum(r.count for r in ranges), summary.frame_count, summary.nucleotide_count,
        summary.nucleotide_fields, expected, separator, separator_after, existed, overwrite,
    )


def _open_verified_index(
    topology: Path, trajectory: Path, index_path: Path, build: bool, *, progress_callback=None
) -> IndexReader:
    """Optionally build, then open an index only after source-integrity checks."""
    if build:
        build_index(topology, trajectory, index_path, progress_callback=progress_callback)
    try:
        return open_index(index_path, topology, trajectory, progress_callback=progress_callback)
    except FileNotFoundError as exc:
        raise ExtractionError(
            "INDEX_NOT_FOUND",
            f"No index at {index_path}. Run the 'index' command first (or pass --build-index when extracting).",
        ) from exc


def _resolve_inputs(topology_path, trajectory_path, index_path, output_path):
    topology = Path(topology_path).resolve()
    trajectory = Path(trajectory_path).resolve()
    index = Path(index_path).resolve() if index_path else default_index_path(trajectory).resolve()
    output = Path(output_path).resolve()
    return topology, trajectory, index, output


def plan_extraction(
    topology_path: str | Path,
    trajectory_path: str | Path,
    frames_spec: str,
    output_path: str | Path,
    *,
    index_path: str | Path | None = None,
    overwrite: bool = False,
) -> ExtractionPlan:
    """Preflight an extraction without creating or changing any file (dry run).

    Requires an existing valid index; a dry run never builds one.
    """
    topology, trajectory, index, output = _resolve_inputs(
        topology_path, trajectory_path, index_path, output_path
    )
    # Reject simple request/output problems before doing the expensive index work.
    parse_frame_ranges(frames_spec)
    _check_output_path(
        output, (("topology", topology), ("trajectory", trajectory), ("index", index)), overwrite
    )
    reader = _open_verified_index(topology, trajectory, index, False)
    with reader:
        return _build_plan(reader, topology, trajectory, index, frames_spec, output, overwrite)


def _copy_range(source, out, start: int, end: int, digest, *, progress_callback=None, progress_base: int = 0, progress_total: int | None = None) -> int:
    """Copy exactly ``[start, end)`` bytes, failing if the indexed source is truncated."""
    source.seek(start)
    buffer = bytearray(min(COPY_CHUNK_BYTES, max(end - start, 1)))
    view = memoryview(buffer)
    remaining = end - start
    while remaining:
        count = source.readinto(view[: min(len(buffer), remaining)])
        if not count:
            raise ExtractionError("SOURCE_TRUNCATED", "Trajectory ended before an indexed frame range was fully read.")
        chunk = view[:count]
        _write_all(out, chunk)
        digest.update(chunk)
        remaining -= count
        if progress_callback is not None:
            progress_callback(progress_base + (end - start - remaining), progress_total or (end - start))
    return end - start


def _verify_output(
    temp_path: Path, plan: ExtractionPlan, expected_sha256: str, *,
    hash_progress_callback=None, validation_progress_callback=None,
) -> None:
    size = temp_path.stat().st_size
    if size != plan.expected_bytes:
        raise ExtractionVerificationError(
            "OUTPUT_SIZE_MISMATCH", f"Output is {size:,} bytes; expected {plan.expected_bytes:,}."
        )
    if _hash_file(temp_path, progress_callback=hash_progress_callback) != expected_sha256:
        raise ExtractionVerificationError(
            "OUTPUT_SHA256_MISMATCH", "Output SHA-256 differs from the bytes read from the source."
        )
    try:
        frames, fields, _, _, _ = validate_trajectory(
            temp_path, plan.nucleotide_count,
            progress_callback=(
                (lambda _frames, current, total: validation_progress_callback(current, total))
                if validation_progress_callback is not None else None
            ),
        )
    except ValidationError as exc:
        raise ExtractionVerificationError("OUTPUT_INVALID", f"Output failed strict validation: {exc}") from exc
    if frames != plan.frames_selected:
        raise ExtractionVerificationError(
            "OUTPUT_FRAME_COUNT_MISMATCH", f"Output has {frames} frame(s); expected {plan.frames_selected}."
        )
    if fields != plan.nucleotide_fields:
        raise ExtractionVerificationError(
            "OUTPUT_FIELD_COUNT_MISMATCH", f"Output records have {fields} fields; expected {plan.nucleotide_fields}."
        )


def _publish_no_clobber(temp_path: Path, destination: Path) -> None:
    """Publish a verified temporary output without replacing an existing destination.

    Raises ``FileExistsError`` when the platform primitive reports an existing
    destination. Windows uses rename semantics; POSIX prefers hard-link
    publication. Filesystems without hard-link support use a documented
    check-then-replace fallback with a small residual race window.
    """
    if os.name == "nt":
        os.rename(temp_path, destination)  # raises FileExistsError on Windows
        return
    try:
        os.link(temp_path, destination)  # raises FileExistsError if present
    except FileExistsError:
        raise
    except OSError:
        # Fallback for filesystems without hard links. A small check-then-replace race remains.
        if destination.exists():
            raise FileExistsError(str(destination))
        os.replace(temp_path, destination)
        return
    try:
        os.unlink(temp_path)
    except OSError:
        pass  # the caller's cleanup removes our own temp file


def extract_frames(
    topology_path: str | Path,
    trajectory_path: str | Path,
    frames_spec: str,
    output_path: str | Path,
    *,
    index_path: str | Path | None = None,
    overwrite: bool = False,
    build_index_if_needed: bool = False,
    progress_callback=None,
    verification_progress_callback=None,
    output_hash_progress_callback=None,
    output_validation_progress_callback=None,
) -> ExtractionResult:
    """Extract frames exactly, verify the result, then publish it atomically."""
    topology, trajectory, index, output = _resolve_inputs(
        topology_path, trajectory_path, index_path, output_path
    )
    parse_frame_ranges(frames_spec)
    _check_output_path(
        output, (("topology", topology), ("trajectory", trajectory), ("index", index)), overwrite
    )
    reader = _open_verified_index(topology, trajectory, index, build_index_if_needed, progress_callback=verification_progress_callback)
    temp_path: Path | None = None
    try:
        with reader:
            plan = _build_plan(reader, topology, trajectory, index, frames_spec, output, overwrite)
            top_before = _stat_identity(topology)
            traj_before = _stat_identity(trajectory)
            fd, temp_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
            temp_path = Path(temp_name)  # unique, created by this process only
            digest = hashlib.sha256()
            written = 0
            with os.fdopen(fd, "wb") as out, trajectory.open("rb") as source:
                for position, rng in enumerate(plan.ranges):
                    written += _copy_range(
                        source, out, reader.offset(rng.start - 1), reader.offset(rng.end), digest,
                        progress_callback=progress_callback, progress_base=written, progress_total=plan.expected_bytes
                    )
                    if plan.separator_after_range == position:
                        _write_all(out, plan.separator)
                        digest.update(plan.separator)
                        written += len(plan.separator)
                out.flush()
                os.fsync(out.fileno())
            if written != plan.expected_bytes:
                raise ExtractionVerificationError(
                    "OUTPUT_SIZE_MISMATCH", f"Wrote {written:,} bytes; expected {plan.expected_bytes:,}."
                )
            if os.name != "nt":
                mask = os.umask(0)
                os.umask(mask)
                os.chmod(temp_path, 0o666 & ~mask)  # mkstemp creates 0600
            expected_sha256 = digest.hexdigest()
            _verify_output(
                temp_path, plan, expected_sha256,
                hash_progress_callback=output_hash_progress_callback,
                validation_progress_callback=output_validation_progress_callback,
            )
            if _stat_identity(topology) != top_before or _stat_identity(trajectory) != traj_before:
                raise ExtractionError(
                    "SOURCE_CHANGED", "A source file changed during extraction; nothing was published."
                )
            if overwrite:
                os.replace(temp_path, output)
            else:
                try:
                    _publish_no_clobber(temp_path, output)
                except FileExistsError as exc:
                    raise OutputPathError(
                        "OUTPUT_EXISTS", f"Output appeared during extraction and was not changed: {output}"
                    ) from exc
            _fsync_directory(output.parent)
    except OSError as exc:
        raise ExtractionError("EXTRACTION_IO_ERROR", f"Extraction I/O failed: {exc}") from exc
    finally:
        # Clean up only this operation's unique temporary file; never remove the requested output.
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
    return ExtractionResult(
        output, topology, trajectory, index, plan.ranges, plan.frames_selected,
        plan.source_frame_count, plan.nucleotide_count, plan.nucleotide_fields,
        written, expected_sha256, len(plan.separator) if plan.separator_after_range is not None else 0,
        plan.output_exists,
    )
