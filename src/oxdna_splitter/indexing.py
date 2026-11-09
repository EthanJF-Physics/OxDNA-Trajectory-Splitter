"""Build and verify reusable frame indexes for oxDNA trajectories.

Topology + trajectory
        ↓
Validate the topology
        ↓
Scan trajectory frames and record byte offsets
        ↓
Write a checksummed temporary index
        ↓
Verify the completed index
        ↓
Publish it for later extraction

An index is only a cache. Reusing one verifies the source-file hashes and the
index checksums before its offsets are trusted.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import mmap
import os
from pathlib import Path
import struct
import tempfile
from typing import BinaryIO
from .validation import (
    FAST_RECORD_MATCHERS,
    ValidationError,
    _decode_record,
    _parse_finite_number,
    _read_bounded_line,
    _tokens,
    validate_topology,
)

MAGIC = b"OXIDX8\0\0"
FORMAT_VERSION = 1
# Binary header layout: format identity/counts followed by checksums for the
# metadata and frame-offset table.
_HEADER = struct.Struct("<8sHHIQQ32s32s")
_OFFSET = struct.Struct("<Q")
_HASH_CHUNK = 1024 * 1024
DEFAULT_INDEX_SUFFIX = ".oxidx"


class IndexErrorBase(Exception):
    """Base class for stable index-related errors."""


class IndexBuildError(IndexErrorBase):
    """An index could not be built and verified safely."""

    pass


class IndexFormatError(IndexErrorBase):
    """An index file is damaged or has an unsupported format."""

    pass


class IndexSourceMismatch(IndexErrorBase):
    """An index does not match the topology or trajectory it was opened with."""

    pass


@dataclass(frozen=True)
class SourceIdentity:
    """Record the file metadata and SHA-256 used to identify one source file."""

    path: str
    size_bytes: int
    mtime_ns: int
    device: int
    inode: int
    sha256: str


@dataclass(frozen=True)
class IndexSummary:
    """Summarize a successfully built or reused trajectory index."""

    index_path: Path
    topology_path: Path
    trajectory_path: Path
    nucleotide_count: int
    frame_count: int
    nucleotide_fields: int
    trajectory_size_bytes: int
    topology_sha256: str
    trajectory_sha256: str
    reused: bool = False


def default_index_path(trajectory_path: str | Path) -> Path:
    path = Path(trajectory_path)
    return path.with_name(path.name + DEFAULT_INDEX_SUFFIX)


def _stat_identity(path: Path) -> tuple[int, int, int, int]:
    st = path.stat()
    return st.st_size, st.st_mtime_ns, getattr(st, "st_dev", 0), getattr(st, "st_ino", 0)


def _hash_file(path: Path, *, progress_callback=None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        processed = 0
        total = path.stat().st_size
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
            processed += len(chunk)
            if progress_callback is not None:
                progress_callback(processed, total)
    return digest.hexdigest()


def _source_identity(path: Path, digest: str) -> SourceIdentity:
    size, mtime_ns, device, inode = _stat_identity(path)
    return SourceIdentity(str(path.resolve()), size, mtime_ns, device, inode, digest)


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


def _scan_trajectory(path: Path, nucleotide_count: int, offset_spool: BinaryIO, *, progress_callback=None) -> tuple[int, int, str, int, str]:
    """Validate/hash a trajectory once while spooling offsets with bounded RAM."""
    digest = hashlib.sha256()
    offset_digest = hashlib.sha256()
    offset = 0
    line = 0
    frame = 0
    field_count: int | None = None
    fast_match = None  # fast-path matcher; set once the first record fixes the field count
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
                if fast_match is not None and fast_match(raw) is not None:
                    # Certainly valid and consistent with field_count (see validation.py);
                    # anything not provably valid takes the strict path below instead.
                    digest.update(raw)
                    offset += len(raw)
                    continue
                text, _ = _decode_record(raw, path, line, offset)
                digest.update(raw)
                fields = _tokens(text, path, line, offset)
                if len(fields) not in (9, 15) or (field_count is not None and len(fields) != field_count):
                    raise ValidationError("INVALID_NUCLEOTIDE_RECORD", "Nucleotide record must contain consistently 9 or 15 numeric fields.", path=path, line_number=line, byte_offset=offset, frame_number=frame + 1, expected="9 or 15 consistent fields", actual=f"{len(fields)} fields")
                field_count = len(fields)
                fast_match = FAST_RECORD_MATCHERS.get(field_count)
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


def _metadata_bytes(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _write_all(handle: BinaryIO, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = handle.write(view)
        if written is None or written <= 0:
            raise OSError("Short write while creating index.")
        view = view[written:]


def _fsync_directory(path: Path) -> None:
    """Best-effort directory sync after publication; unsupported platforms are tolerated."""
    # Directory fsync is available on many POSIX filesystems, but not Windows.
    if os.name == "nt":
        return
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def build_index(
    topology_path: str | Path,
    trajectory_path: str | Path,
    index_path: str | Path | None = None,
    *,
    rebuild: bool = False,
    progress_callback=None,
) -> IndexSummary:
    """Build or safely reuse a checksummed index bound to both source files."""
    topology = Path(topology_path).resolve()
    trajectory = Path(trajectory_path).resolve()
    destination = Path(index_path).resolve() if index_path else default_index_path(trajectory).resolve()
    if destination in (topology, trajectory):
        raise IndexBuildError("Index destination must not be either source file.")
    if destination.exists() and not rebuild:
        try:
            reader = open_index(destination, topology, trajectory, progress_callback=progress_callback)
            try:
                old = reader.summary
                return IndexSummary(
                    old.index_path, old.topology_path, old.trajectory_path,
                    old.nucleotide_count, old.frame_count, old.nucleotide_fields,
                    old.trajectory_size_bytes, old.topology_sha256,
                    old.trajectory_sha256, True,
                )
            finally:
                reader.close()
        except (IndexErrorBase, OSError, ValueError, KeyError, json.JSONDecodeError):
            # A stale or damaged cache is rebuilt; the old file remains untouched
            # until a fully verified replacement is ready.
            pass

    try:
        top_before = _stat_identity(topology)
        traj_before = _stat_identity(trajectory)
        top_info = validate_topology(topology)
        top_hash = _hash_file(topology)
        with tempfile.TemporaryFile(mode="w+b") as offset_spool:
            frame_count, nucleotide_fields, trajectory_hash, trajectory_size, offsets_hash = _scan_trajectory(
                trajectory, top_info.nucleotide_count, offset_spool, progress_callback=progress_callback
            )
            offset_spool.flush()
            offset_spool.seek(0)
            top_after = _stat_identity(topology)
            traj_after = _stat_identity(trajectory)
            if top_before != top_after or traj_before != traj_after:
                raise IndexBuildError("A source file changed while the index was being built; no index was published.")
            top_identity = _source_identity(topology, top_hash)
            traj_identity = _source_identity(trajectory, trajectory_hash)
            if traj_identity.size_bytes != trajectory_size:
                raise IndexBuildError("Trajectory size changed during index construction.")
            metadata = {
                "format": FORMAT_VERSION,
                "topology": top_identity.__dict__,
                "trajectory": traj_identity.__dict__,
                "nucleotide_count": top_info.nucleotide_count,
                "nucleotide_fields": nucleotide_fields,
                "frame_count": frame_count,
                "offset_encoding": "little-endian-uint64",
            }
            metadata_raw = _metadata_bytes(metadata)
            header = _HEADER.pack(
                MAGIC, FORMAT_VERSION, 0, len(metadata_raw), frame_count, frame_count + 1,
                hashlib.sha256(metadata_raw).digest(), bytes.fromhex(offsets_hash),
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
            temp_path = Path(temp_name)
            try:
                with os.fdopen(fd, "wb") as handle:
                    _write_all(handle, header)
                    _write_all(handle, metadata_raw)
                    while chunk := offset_spool.read(_HASH_CHUNK):
                        _write_all(handle, chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
                # Verify the completed candidate before replacing any previous index.
                candidate = _read_index_file(temp_path, topology, trajectory, verify_sources=False)
                candidate.close()
                if _stat_identity(topology) != top_after or _stat_identity(trajectory) != traj_after:
                    raise IndexBuildError("A source file changed before index publication; no index was published.")
                os.replace(temp_path, destination)
                _fsync_directory(destination.parent)
            except BaseException:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                raise
        return IndexSummary(
            destination, topology, trajectory, top_info.nucleotide_count, frame_count,
            nucleotide_fields, traj_identity.size_bytes, top_hash, trajectory_hash, False,
        )
    except ValidationError as exc:
        raise IndexBuildError(str(exc)) from exc
    except OSError as exc:
        raise IndexBuildError(f"Index I/O failed: {exc}") from exc


class IndexReader:
    """Validated index with memory-mapped access to frame boundaries."""
    def __init__(self, path: Path, handle: BinaryIO, mapping: mmap.mmap, metadata: dict, offsets_start: int, summary: IndexSummary):
        self.path = path
        self._handle = handle
        self._mapping = mapping
        self.metadata = metadata
        self._offsets_start = offsets_start
        self.summary = summary

    def offset(self, index: int) -> int:
        if not 0 <= index <= self.summary.frame_count:
            raise IndexError(f"Offset index must be between 0 and {self.summary.frame_count}.")
        return _OFFSET.unpack_from(self._mapping, self._offsets_start + index * _OFFSET.size)[0]

    def frame_range(self, frame_number: int) -> tuple[int, int]:
        """Return [start, end) byte offsets for a one-based frame number."""
        if not 1 <= frame_number <= self.summary.frame_count:
            raise IndexError(f"Frame number must be between 1 and {self.summary.frame_count}.")
        return self.offset(frame_number - 1), self.offset(frame_number)

    def close(self) -> None:
        if self._mapping is not None:
            self._mapping.close()
            self._mapping = None  # type: ignore[assignment]
        if self._handle is not None:
            self._handle.close()
            self._handle = None  # type: ignore[assignment]

    def __enter__(self) -> "IndexReader":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _read_index_file(path: Path, topology: Path, trajectory: Path, *, verify_sources: bool, progress_callback=None) -> IndexReader:
    """Validate index structure/checksums and optionally verify both indexed sources."""
    handle = path.open("rb")
    try:
        size = os.fstat(handle.fileno()).st_size
        if size < _HEADER.size:
            raise IndexFormatError("Index is shorter than its fixed header.")
        mapping = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            fields = _HEADER.unpack_from(mapping, 0)
            magic, version, flags, metadata_len, frame_count, offset_count, metadata_hash, offsets_hash = fields
            if magic != MAGIC or version != FORMAT_VERSION or flags != 0:
                raise IndexFormatError("Unrecognized index signature, version, or flags.")
            if frame_count < 1 or offset_count != frame_count + 1:
                raise IndexFormatError("Index frame/offset counts are inconsistent.")
            metadata_start = _HEADER.size
            offsets_start = metadata_start + metadata_len
            expected_size = offsets_start + offset_count * _OFFSET.size
            if expected_size != size:
                raise IndexFormatError("Index length does not match its declared sections.")
            metadata_raw = mapping[metadata_start:offsets_start]
            if hashlib.sha256(metadata_raw).digest() != metadata_hash:
                raise IndexFormatError("Index metadata checksum mismatch.")
            offsets_view = memoryview(mapping)[offsets_start:]
            if hashlib.sha256(offsets_view).digest() != offsets_hash:
                offsets_view.release()
                raise IndexFormatError("Index offset checksum mismatch.")
            offsets_view.release()
            try:
                metadata = json.loads(metadata_raw.decode("ascii"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise IndexFormatError("Index metadata is not valid ASCII JSON.") from exc
            previous = _OFFSET.unpack_from(mapping, offsets_start)[0]
            if previous != 0:
                raise IndexFormatError("First frame offset must be zero.")
            for i in range(1, offset_count):
                current = _OFFSET.unpack_from(mapping, offsets_start + i * _OFFSET.size)[0]
                if current <= previous:
                    raise IndexFormatError("Frame offsets must increase strictly.")
                previous = current
            if not isinstance(metadata, dict) or not isinstance(metadata.get("trajectory"), dict) or not isinstance(metadata.get("topology"), dict):
                raise IndexFormatError("Index metadata schema is invalid.")
            traj_meta = metadata["trajectory"]
            top_meta = metadata["topology"]
            required_source_fields = {"path", "size_bytes", "mtime_ns", "device", "inode", "sha256"}
            if not required_source_fields.issubset(traj_meta) or not required_source_fields.issubset(top_meta):
                raise IndexFormatError("Index source metadata is incomplete.")
            if previous != int(traj_meta["size_bytes"]):
                raise IndexFormatError("Final frame offset does not equal the recorded trajectory size.")
            if metadata.get("frame_count") != frame_count or metadata.get("offset_encoding") != "little-endian-uint64":
                raise IndexFormatError("Index metadata disagrees with the fixed header.")
            if verify_sources:
                for source, recorded, label in ((topology, top_meta, "topology"), (trajectory, traj_meta, "trajectory")):
                    if str(source.resolve()) != recorded.get("path"):
                        raise IndexSourceMismatch(f"{label.capitalize()} path differs from the indexed source.")
                    try:
                        current_stat = _stat_identity(source)
                    except OSError as exc:
                        raise IndexSourceMismatch(f"Cannot stat {label} source: {exc}") from exc
                    if current_stat[0] != int(recorded["size_bytes"]):
                        raise IndexSourceMismatch(f"{label.capitalize()} size differs from the indexed source.")
                    if _hash_file(source, progress_callback=progress_callback if label == "trajectory" else None) != recorded["sha256"]:
                        raise IndexSourceMismatch(f"{label.capitalize()} SHA-256 differs from the indexed source.")
            summary = IndexSummary(
                path.resolve(), topology.resolve(), trajectory.resolve(),
                int(metadata["nucleotide_count"]), int(frame_count),
                int(metadata["nucleotide_fields"]), int(traj_meta["size_bytes"]),
                str(top_meta["sha256"]), str(traj_meta["sha256"]), True,
            )
            return IndexReader(path, handle, mapping, metadata, offsets_start, summary)
        except BaseException:
            mapping.close()
            raise
    except BaseException:
        handle.close()
        raise


def open_index(index_path: str | Path, topology_path: str | Path, trajectory_path: str | Path, *, progress_callback=None) -> IndexReader:
    """Open an index only after checking its integrity and both source hashes."""
    return _read_index_file(Path(index_path), Path(topology_path).resolve(), Path(trajectory_path).resolve(), verify_sources=True, progress_callback=progress_callback)
