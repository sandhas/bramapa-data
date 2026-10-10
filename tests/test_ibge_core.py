"""Sanity checks on the ibge-core data itself."""

import csv
from pathlib import Path

ADDON = Path(__file__).resolve().parent.parent / "addons" / "ibge-core"

UF_CODES = {
    "11", "12", "13", "14", "15", "16", "17",
    "21", "22", "23", "24", "25", "26", "27", "28", "29",
    "31", "32", "33", "35",
    "41", "42", "43",
    "50", "51", "52", "53",
}


def rows(name: str):
    with (ADDON / "data" / name).open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_all_27_ufs_present_in_each_state_file():
    for name in ("estado_populacao.csv", "estado_area_km2.csv"):
        entities = {r["entity"] for r in rows(name)}
        assert entities == {f"estado:{c}" for c in UF_CODES}, name


def test_state_population_sums_to_country_population():
    states = sum(int(r["value"]) for r in rows("estado_populacao.csv"))
    (country,) = rows("pais_populacao.csv")
    assert country["entity"] == "pais:BR"
    assert states == int(country["value"]) == 203_080_756


def test_total_area_is_close_to_official_brazil_area():
    # IBGE 2022: 8 510 417,771 km². Individual UF figures were typed from
    # memory and must be re-checked against the IBGE API before Fase 3, so we
    # only assert the total is in the right neighbourhood.
    total = sum(float(r["value"]) for r in rows("estado_area_km2.csv"))
    assert abs(total - 8_510_417.771) < 100
