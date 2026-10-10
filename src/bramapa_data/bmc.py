"""Minimal ``.bmc`` chunk codec (spec: bramapa/docs/spec/chunk.md).

Only what overrides need: read a chunk, edit layers, write it back. The full
pipeline codec lives in bramapa-pipeline; this one is kept dependency-light
(stdlib + zstandard) so the data repo stays small.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import zstandard

MAGIC = b"BMCK"
HEADER = struct.Struct("<4sHHHBBiiiiI")
NO_PERIOD = -(2**31)
FLAG_OBJECTS = 1
FLAG_ENTITY = 2


@dataclass
class Chunk:
    cx: int
    cy: int
    size: int = 64
    terrain: list[int] = field(default_factory=list)
    overlay: list[int] = field(default_factory=list)
    entity: list[int] | None = None
    objects: list[tuple[int, int, int, int]] = field(default_factory=list)  # (x, y, tile, flags)
    period_start: int = NO_PERIOD
    period_end: int = NO_PERIOD

    @classmethod
    def empty(cls, cx: int, cy: int, size: int = 64) -> "Chunk":
        n = size * size
        return cls(cx, cy, size, [0] * n, [0] * n)

    def idx(self, x: int, y: int) -> int:
        return y * self.size + x


def decode(data: bytes) -> Chunk:
    magic, version, flags, size, layer_count, _res, cx, cy, ps, pe, payload_len = HEADER.unpack_from(data, 0)
    if magic != MAGIC or version != 0:
        raise ValueError("not a spec v0 .bmc file")
    if len(data) != HEADER.size + payload_len:
        raise ValueError("payload length mismatch")
    raw = zstandard.ZstdDecompressor().decompress(data[HEADER.size :])
    n = size * size
    has_objects = bool(flags & FLAG_OBJECTS)
    has_entity = bool(flags & FLAG_ENTITY)
    if layer_count != 2 + has_objects + has_entity:
        raise ValueError("layer_count inconsistent with flags")
    pos = 0

    def layer() -> list[int]:
        nonlocal pos
        vals = list(struct.unpack_from(f"<{n}H", raw, pos))
        pos += n * 2
        return vals

    terrain = layer()
    overlay = layer()
    entity = layer() if has_entity else None
    objects: list[tuple[int, int, int, int]] = []
    if has_objects:
        (count,) = struct.unpack_from("<I", raw, pos)
        pos += 4
        for _ in range(count):
            x, y, tile, oflags, _r = struct.unpack_from("<BBHHH", raw, pos)
            pos += 8
            objects.append((x, y, tile, oflags))
    return Chunk(cx, cy, size, terrain, overlay, entity, objects, ps, pe)


def encode(chunk: Chunk) -> bytes:
    n = chunk.size * chunk.size
    raw = bytearray()
    raw += struct.pack(f"<{n}H", *chunk.terrain)
    raw += struct.pack(f"<{n}H", *chunk.overlay)
    flags = 0
    if chunk.entity is not None:
        raw += struct.pack(f"<{n}H", *chunk.entity)
        flags |= FLAG_ENTITY
    if chunk.objects:
        flags |= FLAG_OBJECTS
        raw += struct.pack("<I", len(chunk.objects))
        for x, y, tile, oflags in sorted(chunk.objects, key=lambda o: (o[0] + o[1], o[1], o[0])):
            raw += struct.pack("<BBHHH", x, y, tile, oflags, 0)
    payload = zstandard.ZstdCompressor(level=3, write_content_size=True, write_checksum=False).compress(bytes(raw))
    layer_count = 2 + bool(flags & FLAG_OBJECTS) + bool(flags & FLAG_ENTITY)
    header = HEADER.pack(
        MAGIC, 0, flags, chunk.size, layer_count, 0, chunk.cx, chunk.cy, chunk.period_start, chunk.period_end, len(payload)
    )
    return header + payload
