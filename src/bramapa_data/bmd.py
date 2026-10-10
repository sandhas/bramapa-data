"""The ``.bmd`` columnar binary format (``docs/spec/data-binary.md``, spec v0).

Layout, little-endian throughout:

* 24-byte header: magic ``"BMDT"``, ``u16 spec_version = 0``, ``u8 dtype``
  (0 = i64, 1 = f64, 2 = str), ``u8 reserved = 0``, ``u32 row_count``,
  ``u32 entity_count``, ``u32 string_count``, ``u32 payload_len``.
* zstd frame of ``payload_len`` bytes which decompresses to: the entity string
  table (``entity_count`` strings, each ``u32 len`` + UTF-8), the value string
  table when dtype = str (``string_count`` strings), then the columns
  ``entity_idx: u32[]``, ``period_start: i32[]``, ``period_end: i32[]`` (days
  since 1970-01-01, inclusive) and ``value: i64[] | f64[] | u32[]``.

Decisions the spec leaves open, fixed here so the Rust reader can rely on them:

* Entity table order is the lexicographic (byte-wise) order of the entity ids,
  so index assignment is deterministic. The string table is likewise sorted
  and deduplicated.
* Rows are sorted by ``(entity_idx, period_start, period_end)``; the spec only
  requires ``(entity_idx, period_start)``, the third key breaks ties.
* The zstd frame is a single frame, level 3, with the content size written and
  no checksum, so the output is byte-for-byte reproducible.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from datetime import date, timedelta

import zstandard

MAGIC = b"BMDT"
SPEC_VERSION = 0
HEADER = struct.Struct("<4sHBBIIII")
HEADER_SIZE = HEADER.size  # 24
assert HEADER_SIZE == 24

DTYPE_CODES = {"i64": 0, "f64": 1, "str": 2}
DTYPE_NAMES = {code: name for name, code in DTYPE_CODES.items()}
VALUE_FORMATS = {"i64": "q", "f64": "d", "str": "I"}

EPOCH = date(1970, 1, 1)
ZSTD_LEVEL = 3
U32_MAX = 2**32 - 1
I32_MIN, I32_MAX = -(2**31), 2**31 - 1


def days_since_epoch(day: date) -> int:
    """``date`` → days since 1970-01-01 (negative before the epoch)."""
    return (day - EPOCH).days


def date_from_days(days: int) -> date:
    return EPOCH + timedelta(days=days)


@dataclass(frozen=True)
class Row:
    """One data point: entity id, inclusive day range, value of the property's dtype."""

    entity: str
    period_start: int
    period_end: int
    value: int | float | str


@dataclass(frozen=True)
class Header:
    dtype: str
    row_count: int
    entity_count: int
    string_count: int
    payload_len: int
    spec_version: int = SPEC_VERSION

    def pack(self) -> bytes:
        return HEADER.pack(
            MAGIC,
            self.spec_version,
            DTYPE_CODES[self.dtype],
            0,
            self.row_count,
            self.entity_count,
            self.string_count,
            self.payload_len,
        )

    @classmethod
    def unpack(cls, data: bytes) -> Header:
        if len(data) < HEADER_SIZE:
            raise ValueError(f"file too short for a .bmd header ({len(data)} bytes)")
        magic, spec_version, dtype_code, reserved, rows, entities, strings, payload_len = HEADER.unpack_from(data)
        if magic != MAGIC:
            raise ValueError(f"bad magic {magic!r} (expected {MAGIC!r})")
        if spec_version != SPEC_VERSION:
            raise ValueError(f"unknown spec_version {spec_version}")
        if dtype_code not in DTYPE_NAMES:
            raise ValueError(f"unknown dtype code {dtype_code}")
        if reserved != 0:
            raise ValueError(f"reserved byte is {reserved}, expected 0")
        return cls(DTYPE_NAMES[dtype_code], rows, entities, strings, payload_len, spec_version)


@dataclass(frozen=True)
class Decoded:
    header: Header
    entities: list[str]
    strings: list[str]
    rows: list[Row]  # values already resolved (str rows carry the string, not the index)


def _pack_string_table(strings: list[str]) -> bytes:
    out = bytearray()
    for s in strings:
        raw = s.encode("utf-8")
        out += struct.pack("<I", len(raw))
        out += raw
    return bytes(out)


def _check_u32(value: int, what: str) -> None:
    if not 0 <= value <= U32_MAX:
        raise ValueError(f"{what} {value} does not fit in u32")


def encode(rows: list[Row], dtype: str) -> bytes:
    """Serialize ``rows`` as a complete ``.bmd`` file (header + zstd payload)."""
    if dtype not in DTYPE_CODES:
        raise ValueError(f"unknown dtype {dtype!r}")

    entities = sorted({r.entity for r in rows})
    entity_idx = {e: i for i, e in enumerate(entities)}

    strings: list[str] = []
    string_idx: dict[str, int] = {}
    if dtype == "str":
        strings = sorted({str(r.value) for r in rows})
        string_idx = {s: i for i, s in enumerate(strings)}

    ordered = sorted(rows, key=lambda r: (entity_idx[r.entity], r.period_start, r.period_end))
    n = len(ordered)
    _check_u32(n, "row_count")
    _check_u32(len(entities), "entity_count")
    _check_u32(len(strings), "string_count")
    for r in ordered:
        for d in (r.period_start, r.period_end):
            if not I32_MIN <= d <= I32_MAX:
                raise ValueError(f"period day {d} does not fit in i32")

    payload = bytearray()
    payload += _pack_string_table(entities)
    if dtype == "str":
        payload += _pack_string_table(strings)
    payload += struct.pack(f"<{n}I", *(entity_idx[r.entity] for r in ordered))
    payload += struct.pack(f"<{n}i", *(r.period_start for r in ordered))
    payload += struct.pack(f"<{n}i", *(r.period_end for r in ordered))
    if dtype == "i64":
        payload += struct.pack(f"<{n}q", *(int(r.value) for r in ordered))
    elif dtype == "f64":
        payload += struct.pack(f"<{n}d", *(float(r.value) for r in ordered))
    else:
        payload += struct.pack(f"<{n}I", *(string_idx[str(r.value)] for r in ordered))

    compressor = zstandard.ZstdCompressor(level=ZSTD_LEVEL, write_content_size=True, write_checksum=False)
    compressed = compressor.compress(bytes(payload))
    _check_u32(len(compressed), "payload_len")

    header = Header(dtype, n, len(entities), len(strings), len(compressed))
    return header.pack() + compressed


def _read_string_table(buf: bytes, offset: int, count: int) -> tuple[list[str], int]:
    out = []
    for _ in range(count):
        (length,) = struct.unpack_from("<I", buf, offset)
        offset += 4
        out.append(buf[offset : offset + length].decode("utf-8"))
        offset += length
    return out, offset


def decode(data: bytes) -> Decoded:
    """Parse a complete ``.bmd`` file. Inverse of :func:`encode`."""
    header = Header.unpack(data)
    compressed = data[HEADER_SIZE : HEADER_SIZE + header.payload_len]
    if len(compressed) != header.payload_len:
        raise ValueError(f"payload truncated: header says {header.payload_len} bytes, got {len(compressed)}")
    if len(data) != HEADER_SIZE + header.payload_len:
        raise ValueError(f"{len(data) - HEADER_SIZE - header.payload_len} trailing bytes after payload")
    buf = zstandard.ZstdDecompressor().decompressobj().decompress(compressed)

    n = header.row_count
    entities, offset = _read_string_table(buf, 0, header.entity_count)
    strings: list[str] = []
    if header.dtype == "str":
        strings, offset = _read_string_table(buf, offset, header.string_count)
    idx = struct.unpack_from(f"<{n}I", buf, offset)
    offset += 4 * n
    starts = struct.unpack_from(f"<{n}i", buf, offset)
    offset += 4 * n
    ends = struct.unpack_from(f"<{n}i", buf, offset)
    offset += 4 * n
    fmt = VALUE_FORMATS[header.dtype]
    values = struct.unpack_from(f"<{n}{fmt}", buf, offset)
    offset += struct.calcsize(fmt) * n
    if offset != len(buf):
        raise ValueError(f"payload has {len(buf) - offset} unexpected trailing bytes")

    rows = []
    for i in range(n):
        value: int | float | str = values[i]
        if header.dtype == "str":
            value = strings[values[i]]
        rows.append(Row(entities[idx[i]], starts[i], ends[i], value))
    return Decoded(header, entities, strings, rows)
