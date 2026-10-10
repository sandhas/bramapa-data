"""Sanity checks on the ibge-core data itself (fetched by tools/fetch_ibge.py)."""

import csv
from collections import defaultdict
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


def by_year(name: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for r in rows(name):
        out[r["period_start"]][r["entity"]] = r["value"]
    return out


def test_all_27_ufs_present_in_every_year_of_each_state_file():
    for name in ("estado_populacao.csv", "estado_area_km2.csv", "estado_pib.csv"):
        years = by_year(name)
        assert years, name
        for year, values in years.items():
            assert set(values) == {f"estado:{c}" for c in UF_CODES}, (name, year)


def test_population_covers_estimates_and_census_2022():
    years = set(by_year("estado_populacao.csv"))
    assert "2022" in years  # Censo 2022 (SIDRA 4714), absent from the estimates table
    assert {"2001", "2021", "2024"} <= years  # SIDRA 6579 estimates
    assert "2010" not in years  # census year without estimate; not fetched (yet)
    assert years == set(by_year("pais_populacao.csv"))


def test_state_population_sums_to_country_population_every_year():
    states = by_year("estado_populacao.csv")
    country = by_year("pais_populacao.csv")
    for year, values in states.items():
        assert sum(int(v) for v in values.values()) == int(country[year]["pais:BR"]), year
    assert int(country["2022"]["pais:BR"]) == 203_080_756


def test_state_pib_sums_to_country_pib_within_rounding():
    states = by_year("estado_pib.csv")
    country = by_year("pais_pib.csv")
    assert set(states) == set(country)
    assert {"2002", "2023"} <= set(states)
    for year, values in states.items():
        # SIDRA publishes each UF rounded to R$ mil; the sum drifts by a few units.
        assert abs(sum(int(v) for v in values.values()) - int(country[year]["pais:BR"])) <= 30, year


def test_total_area_matches_official_brazil_area():
    # SIDRA 4714 v/6318 for Brasil: 8 510 417,771 km²; UF values sum to within rounding.
    total = sum(float(r["value"]) for r in rows("estado_area_km2.csv"))
    assert abs(total - 8_510_417.771) < 0.01
    assert {r["period_start"] for r in rows("estado_area_km2.csv")} == {"2022"}
