#!/usr/bin/env python3
"""Fetch the ibge-core series from the IBGE SIDRA API and rewrite the addon CSVs.

Public API, no key needed. Pure stdlib. Run from the repo root::

    uv run python tools/fetch_ibge.py            # rewrite addons/ibge-core/data/*.csv
    uv run python tools/fetch_ibge.py --dry-run  # fetch and report, do not write

Tables used (https://sidra.ibge.gov.br/tabela/<n>):

* 6579 v/9324 — Estimativas da população residente (annual, 2001..latest; the
  census/count years 2007, 2010, 2022 and the skipped 2023 have no estimate).
* 4714 v/93   — Censo Demográfico 2022, população residente (2022 only).
* 4714 v/6318 — Área territorial (km², 2022).
* 5938 v/37   — PIB a preços correntes, "Mil Reais" (annual, 2002..latest).

Merge rule for ``populacao``: the Censo 2022 figure wins over any 6579 value
for 2022 (there is none today; if IBGE ever publishes one, the census still
wins and the addon README says so).

Response shape (per element after the header row): ``D1C`` = territory code
(UF code for n3, "1" for Brasil n1), ``D3C`` = year, ``V`` = value as text,
``MN`` = unit name.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://apisidra.ibge.gov.br/values"
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "addons" / "ibge-core" / "data"
CSV_HEADER = ["entity", "period_start", "period_end", "value"]

UF_CODES = {
    "11", "12", "13", "14", "15", "16", "17",
    "21", "22", "23", "24", "25", "26", "27", "28", "29",
    "31", "32", "33", "35",
    "41", "42", "43",
    "50", "51", "52", "53",
}


def fetch(table: int, level: str, variable: int, periods: str = "all") -> list[dict[str, str]]:
    """Return the data rows (header row dropped) of one SIDRA query."""
    url = f"{API}/t/{table}/{level}/all/v/{variable}/p/{periods}?formato=json"
    print(f"GET {url}", file=sys.stderr)
    req = urllib.request.Request(url, headers={"User-Agent": "bramapa-data/fetch_ibge"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.load(resp)
    except urllib.error.URLError as exc:
        sys.exit(f"error: SIDRA request failed for table {table} ({level}): {exc}")
    if not isinstance(payload, list) or len(payload) < 2:
        sys.exit(f"error: unexpected SIDRA response for table {table} ({level}): {payload!r:.200}")
    header, rows = payload[0], payload[1:]
    if header.get("D3N") != "Ano" or header.get("V") != "Valor":
        sys.exit(f"error: unexpected dimension order in table {table}: {header}")
    return rows


def entity_id(level: str, row: dict[str, str]) -> str:
    if level == "n1":
        return "pais:BR"
    code = row["D1C"]
    if code not in UF_CODES:
        sys.exit(f"error: unknown UF code {code!r} in SIDRA row {row}")
    return f"estado:{code}"


def series(table: int, level: str, variable: int, unit: str, cast) -> dict[tuple[str, str], str]:
    """``{(entity, year): value_text}`` for one table/level, with unit and dtype checks."""
    out: dict[tuple[str, str], str] = {}
    for row in fetch(table, level, variable):
        if row["MN"] != unit:
            sys.exit(f"error: table {table} v/{variable} unit is {row['MN']!r}, expected {unit!r}")
        value = row["V"]
        try:
            cast(value)
        except ValueError:
            sys.exit(f"error: table {table} value {value!r} is not {cast.__name__}")
        key = (entity_id(level, row), row["D3C"])
        if key in out:
            sys.exit(f"error: table {table} repeated key {key}")
        out[key] = value
    return out


def write_csv(path: Path, data: dict[tuple[str, str], str], dry_run: bool) -> None:
    rows = sorted(data.items())  # (entity, year) lexicographic: deterministic file
    years = sorted({y for (_, y) in data})
    entities = {e for (e, _) in data}
    print(
        f"{path.relative_to(REPO_ROOT)}: {len(rows)} rows, {len(entities)} entities, "
        f"years {years[0]}..{years[-1]} ({len(years)} distinct)",
        file=sys.stderr,
    )
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(CSV_HEADER)
        for (entity, year), value in rows:
            writer.writerow([entity, year, year, value])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="fetch and report; do not write CSVs")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help=f"output directory (default {DATA_DIR})")
    args = parser.parse_args(argv)

    for level, prefix in (("n3", "estado"), ("n1", "pais")):
        # populacao: estimates + census 2022 (census wins on conflict)
        pop = series(6579, level, 9324, "Pessoas", int)
        census = series(4714, level, 93, "Pessoas", int)
        for key, value in census.items():
            if key in pop and pop[key] != value:
                print(f"note: {key} has both estimate {pop[key]} and census {value}; keeping census", file=sys.stderr)
            pop[key] = value
        write_csv(args.data_dir / f"{prefix}_populacao.csv", pop, args.dry_run)

        # pib: "Mil Reais", integer text in SIDRA
        pib = series(5938, level, 37, "Mil Reais", int)
        write_csv(args.data_dir / f"{prefix}_pib.csv", pib, args.dry_run)

    # area: UFs only (the country total is the sum; the engine can derive it)
    area = series(4714, "n3", 6318, "Quilômetros quadrados", float)
    write_csv(args.data_dir / "estado_area_km2.csv", area, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
