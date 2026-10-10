"""Map overrides: codec round-trip, build copies chunks and lists them in index.toml."""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

from bramapa_data.bmc import Chunk, decode, encode
from bramapa_data.build import build

ROOT = Path(__file__).resolve().parents[1]


def test_bmc_roundtrip_with_entity_and_objects() -> None:
    c = Chunk.empty(3, 2)
    c.terrain[c.idx(1, 1)] = 6
    c.overlay[c.idx(2, 2)] = 20
    c.entity = [0] * (64 * 64)
    c.entity[c.idx(5, 5)] = 9
    c.objects = [(5, 5, 41, 0), (1, 1, 40, 1)]
    data = encode(c)
    assert data[:4] == b"BMCK" and data[6] == 3 and data[10] == 4
    d = decode(data)
    assert d.cx == 3 and d.cy == 2
    assert d.terrain[d.idx(1, 1)] == 6 and d.overlay[d.idx(2, 2)] == 20
    assert d.entity is not None and d.entity[d.idx(5, 5)] == 9
    assert sorted(d.objects) == sorted(c.objects)
    # canonical: no entity, no objects -> flags 0, 2 layers
    e = encode(Chunk.empty(0, 0))
    assert e[6] == 0 and e[10] == 2


def test_build_copies_override_chunks_and_indexes_them(tmp_path: Path) -> None:
    addons = tmp_path / "addons"
    shutil.copytree(ROOT / "addons" / "ibge-core", addons / "ibge-core")
    ov = addons / "ovr-exemplo"
    (ov / "map" / "centro").mkdir(parents=True)
    (ov / "map" / "centro" / "8_7.bmc").write_bytes(encode(Chunk.empty(8, 7)))
    (ov / "manifest.toml").write_text(
        """
spec_version = 0
[addon]
id = "ovr-exemplo"
name = "Override de exemplo"
version = "0.1.0"
license = "CC-BY-4.0"
[[map_overrides]]
level = 3
entity = "municipio:4314902"
path = "map/centro"
chunks = [[8, 7]]
priority = 10
""",
        encoding="utf-8",
    )
    out = tmp_path / "build"
    result = build(addons, out)
    assert len(result.overrides) == 1
    assert (out / "ovr-exemplo" / "map" / "centro" / "8_7.bmc").is_file()
    index = tomllib.loads((out / "index.toml").read_text(encoding="utf-8"))
    (entry,) = index["map_overrides"]
    assert entry == {
        "addon": "ovr-exemplo",
        "level": 3,
        "entity": "municipio:4314902",
        "path": "ovr-exemplo/map/centro",
        "chunks": [[8, 7]],
        "priority": 10,
    }
