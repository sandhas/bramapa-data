#!/usr/bin/env python
"""Generate an example manual override: a small "plaza" stamped into the chunk that
contains a lon/lat point of an existing level.

    uv run --group tools python tools/make_override.py \
        --level ../bramapa-levels/3/municipio_4314902 --lon -51.2300 --lat -30.0330 \
        --out addons/poa-centro-exemplo/map/centro

It reads the level's projection from level.toml, converts the point to grid cells,
copies the original chunk (keeping its entity layer) and redraws the central block:
urban ground, a cross of avenues, a park with trees and a ring of buildings. Prints
the chunk coordinates to paste into the addon manifest.
"""

from __future__ import annotations

import argparse
import math
import sys
import tomllib
from pathlib import Path

from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bramapa_data.bmc import decode, encode  # noqa: E402

# Placeholder tile ids (tileset.md, "Ids de tile do placeholder v0").
CAMPO, URBANO, FLORESTA = 1, 6, 4
RODOVIA = 20
ARVORE, PREDIO, CASA = 40, 41, 42


def lonlat_to_cell(level: dict, lon: float, lat: float) -> tuple[float, float]:
    proj = level["projection"]
    grid = level["grid"]
    tr = Transformer.from_crs("EPSG:4326", proj["crs"], always_xy=True)
    e, n = tr.transform(lon, lat)
    c = float(grid["cell_meters"])
    if abs(float(proj["rotation_deg"]) - 45.0) > 1e-6:
        raise SystemExit("only rotation_deg = 45 is supported")
    a = (e - float(proj["origin_x"])) * math.sqrt(2) / c  # x - y
    b = (float(proj["origin_y"]) - n) * math.sqrt(2) / c  # x + y
    return (a + b) / 2, (b - a) / 2


def stamp_plaza(chunk, cx_local: int, cy_local: int, half: int = 14) -> None:
    s = chunk.size
    x0, x1 = max(0, cx_local - half), min(s - 1, cx_local + half)
    y0, y1 = max(0, cy_local - half), min(s - 1, cy_local + half)
    chunk.objects = [o for o in chunk.objects if not (x0 <= o[0] <= x1 and y0 <= o[1] <= y1)]
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            i = chunk.idx(x, y)
            dx, dy = x - cx_local, y - cy_local
            r = max(abs(dx), abs(dy))
            chunk.overlay[i] = 0
            if r <= 4:
                chunk.terrain[i] = CAMPO  # central park
                if (x + y) % 3 == 0 and r >= 2:
                    chunk.objects.append((x, y, ARVORE, 0))
            else:
                chunk.terrain[i] = URBANO
                if dx == 0 or dy == 0:
                    chunk.overlay[i] = RODOVIA  # avenues crossing the plaza
                elif r in (6, 7):
                    chunk.objects.append((x, y, PREDIO, 0))  # ring of towers
                elif (x * 7 + y * 13) % 5 == 0:
                    chunk.objects.append((x, y, CASA, (x + y) & 1))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--level", required=True, type=Path)
    ap.add_argument("--lon", required=True, type=float)
    ap.add_argument("--lat", required=True, type=float)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    level = tomllib.loads((args.level / "level.toml").read_text(encoding="utf-8"))
    cs = int(level["grid"]["chunk_size"])
    x, y = lonlat_to_cell(level, args.lon, args.lat)
    if not (0 <= x < level["grid"]["width"] and 0 <= y < level["grid"]["height"]):
        raise SystemExit(f"point falls outside the grid at cell ({x:.1f}, {y:.1f})")
    cx, cy = int(x) // cs, int(y) // cs
    src = args.level / "chunks" / f"{cx}_{cy}.bmc"
    chunk = decode(src.read_bytes())
    stamp_plaza(chunk, int(x) % cs, int(y) % cs)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{cx}_{cy}.bmc").write_bytes(encode(chunk))
    print(f"cell ({x:.1f}, {y:.1f}) -> chunk [{cx}, {cy}] written to {args.out / f'{cx}_{cy}.bmc'}")
    print(f'manifest: level = {level["level"]["level"]}, entity = "{level["level"]["entity"]}", chunks = [[{cx}, {cy}]]')


if __name__ == "__main__":
    main()
