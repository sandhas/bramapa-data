"""Builder: .bmd byte layout, sorting, determinism, index.toml, inspect."""

from __future__ import annotations

import filecmp
import struct
import tomllib
from datetime import date
from pathlib import Path

import pytest
import zstandard

from bramapa_data.bmd import Row, date_from_days, days_since_epoch, encode
from bramapa_data.build import BuildError, build
from bramapa_data.cli import main

# -- an independent reader, written straight from docs/spec/data-binary.md ----


def read_bmd(path: Path) -> dict:
    """Decode a .bmd with struct only, not through bramapa_data.bmd.decode."""
    data = path.read_bytes()
    magic, spec_version, dtype, reserved, rows, entities, strings, payload_len = struct.unpack_from(
        "<4sHBBIIII", data, 0
    )
    assert magic == b"BMDT"
    assert spec_version == 0
    assert reserved == 0
    assert len(data) == 24 + payload_len
    buf = zstandard.ZstdDecompressor().decompress(data[24:])  # content size is written in the frame

    pos = 0

    def table(count):
        nonlocal pos
        out = []
        for _ in range(count):
            (n,) = struct.unpack_from("<I", buf, pos)
            pos += 4
            out.append(buf[pos : pos + n].decode("utf-8"))
            pos += n
        return out

    entity_table = table(entities)
    string_table = table(strings) if dtype == 2 else []
    assert dtype == 2 or strings == 0
    idx = struct.unpack_from(f"<{rows}I", buf, pos)
    pos += 4 * rows
    starts = struct.unpack_from(f"<{rows}i", buf, pos)
    pos += 4 * rows
    ends = struct.unpack_from(f"<{rows}i", buf, pos)
    pos += 4 * rows
    fmt = {0: "q", 1: "d", 2: "I"}[dtype]
    values = struct.unpack_from(f"<{rows}{fmt}", buf, pos)
    pos += struct.calcsize(fmt) * rows
    assert pos == len(buf), "payload has trailing bytes"
    return {
        "dtype": dtype,
        "entities": entity_table,
        "strings": string_table,
        "idx": list(idx),
        "starts": list(starts),
        "ends": list(ends),
        "values": list(values),
    }


# -- fixture addon ---------------------------------------------------------

MANIFEST = """\
spec_version = 0

[addon]
id = "mini"
name = "Mini"
version = "1.2.3"
license = "CC0-1.0"

[[properties]]
id = "pop"
entity_type = "estado"
name = "População"
unit = "habitantes"
dtype = "i64"
periodicity = "anual"
source = "teste"
file = "data/pop.csv"

[[properties]]
id = "area"
entity_type = "estado"
name = "Área"
unit = "km²"
dtype = "f64"
periodicity = "pontual"
source = "teste"
file = "data/area.csv"

[[properties]]
id = "capital"
entity_type = "estado"
name = "Capital"
unit = ""
dtype = "str"
periodicity = "pontual"
source = "teste"
file = "data/capital.csv"

[[properties]]
id = "vazia"
entity_type = "pais"
name = "Sem linhas"
unit = ""
dtype = "i64"
periodicity = "pontual"
source = "teste"
file = "data/vazia.csv"
"""

# Deliberately unsorted: entity 43 before 11, 2023 before 2022, blank line, empty value.
POP_CSV = """\
entity,period_start,period_end,value
estado:43,2023,,10900000
estado:43,2022,2022,10882965

estado:11,2022-03,,1581196
estado:11,2022,2022,1581000
estado:35,2022,2022,
estado:35,2000-02-29,2000-02-29,-5
"""

AREA_CSV = """\
entity,period_start,period_end,value
estado:43,2022,2022,281707.151
estado:11,2022,2022,237754.172
"""

CAPITAL_CSV = """\
entity,period_start,period_end,value
estado:43,2022,2022,Porto Alegre
estado:11,2022,2022,Porto Velho
estado:35,2022,2022,São Paulo
estado:53,2022,2022,Brasília
estado:12,2022,2022,Rio Branco
estado:13,2022,2022,Manaus
"""


@pytest.fixture
def mini_addons(tmp_path: Path) -> Path:
    addons = tmp_path / "addons"
    data = addons / "mini" / "data"
    data.mkdir(parents=True)
    (addons / "mini" / "manifest.toml").write_text(MANIFEST, encoding="utf-8")
    (data / "pop.csv").write_text(POP_CSV, encoding="utf-8")
    (data / "area.csv").write_text(AREA_CSV, encoding="utf-8")
    (data / "capital.csv").write_text(CAPITAL_CSV, encoding="utf-8")
    (data / "vazia.csv").write_text("entity,period_start,period_end,value\n", encoding="utf-8")
    return addons


# -- period → days ---------------------------------------------------------


def test_year_2022_is_days_18993_to_19357():
    assert days_since_epoch(date(2022, 1, 1)) == 18993
    assert days_since_epoch(date(2022, 12, 31)) == 19357
    assert days_since_epoch(date(1970, 1, 1)) == 0
    assert days_since_epoch(date(1969, 12, 31)) == -1
    assert date_from_days(18993) == date(2022, 1, 1)


# -- encode() directly -----------------------------------------------------


def test_encode_header_layout_and_columns(tmp_path: Path):
    rows = [
        Row("estado:43", 18993, 19357, 10),
        Row("estado:11", 18993, 19357, 20),
        Row("estado:11", 18628, 18992, 30),  # 2021, must sort before 2022
    ]
    out = tmp_path / "x.bmd"
    out.write_bytes(encode(rows, "i64"))
    got = read_bmd(out)
    assert got["dtype"] == 0
    assert got["entities"] == ["estado:11", "estado:43"]  # lexicographic
    assert got["idx"] == [0, 0, 1]
    assert got["starts"] == [18628, 18993, 18993]
    assert got["ends"] == [18992, 19357, 19357]
    assert got["values"] == [30, 20, 10]


def test_encode_rejects_unknown_dtype():
    with pytest.raises(ValueError):
        encode([], "u8")


# -- build() end to end ------------------------------------------------------


def test_build_writes_expected_tree(mini_addons: Path, tmp_path: Path):
    out = tmp_path / "out"
    result = build(mini_addons, out)
    assert sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()) == [
        "index.toml",
        "mini/estado/area.bmd",
        "mini/estado/capital.bmd",
        "mini/estado/pop.bmd",
        "mini/manifest.toml",
        "mini/pais/vazia.bmd",
    ]
    assert filecmp.cmp(mini_addons / "mini" / "manifest.toml", out / "mini" / "manifest.toml", shallow=False)
    by_id = {p.id: p for p in result.properties}
    assert by_id["mini/estado/pop"].rows == 5  # 6 data lines, one empty value dropped
    assert by_id["mini/pais/vazia"].rows == 0


def test_build_i64_rows_sorted_by_entity_then_period(mini_addons: Path, tmp_path: Path):
    out = tmp_path / "out"
    build(mini_addons, out)
    got = read_bmd(out / "mini" / "estado" / "pop.bmd")
    assert got["entities"] == ["estado:11", "estado:35", "estado:43"]
    y2022 = (18993, 19357)
    mar2022 = (days_since_epoch(date(2022, 3, 1)), days_since_epoch(date(2022, 3, 31)))
    y2023 = (days_since_epoch(date(2023, 1, 1)), days_since_epoch(date(2023, 12, 31)))
    leap = days_since_epoch(date(2000, 2, 29))
    assert list(zip(got["idx"], got["starts"], got["ends"], got["values"])) == [
        (0, *y2022, 1581000),
        (0, *mar2022, 1581196),
        (1, leap, leap, -5),
        (2, *y2022, 10882965),
        (2, *y2023, 10900000),
    ]


def test_build_f64_values(mini_addons: Path, tmp_path: Path):
    out = tmp_path / "out"
    build(mini_addons, out)
    got = read_bmd(out / "mini" / "estado" / "area.bmd")
    assert got["dtype"] == 1
    assert got["entities"] == ["estado:11", "estado:43"]
    assert got["values"] == [237754.172, 281707.151]


def test_build_str_dtype_uses_sorted_string_table(mini_addons: Path, tmp_path: Path):
    out = tmp_path / "out"
    build(mini_addons, out)
    got = read_bmd(out / "mini" / "estado" / "capital.bmd")
    assert got["dtype"] == 2
    assert got["strings"] == sorted(got["strings"])
    assert set(got["strings"]) == {"Porto Alegre", "Porto Velho", "São Paulo", "Brasília", "Rio Branco", "Manaus"}
    resolved = {got["entities"][i]: got["strings"][v] for i, v in zip(got["idx"], got["values"])}
    assert resolved == {
        "estado:11": "Porto Velho",
        "estado:12": "Rio Branco",
        "estado:13": "Manaus",
        "estado:35": "São Paulo",
        "estado:43": "Porto Alegre",
        "estado:53": "Brasília",
    }
    header = struct.unpack_from("<4sHBBIIII", (out / "mini" / "estado" / "capital.bmd").read_bytes())
    assert header[6] == 6  # string_count


def test_build_empty_property_has_zero_rows(mini_addons: Path, tmp_path: Path):
    out = tmp_path / "out"
    build(mini_addons, out)
    got = read_bmd(out / "mini" / "pais" / "vazia.bmd")
    assert got["entities"] == [] and got["idx"] == []


def test_build_is_deterministic(mini_addons: Path, tmp_path: Path):
    a, b = tmp_path / "a", tmp_path / "b"
    build(mini_addons, a)
    build(mini_addons, b)
    files = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    assert files
    for rel in files:
        assert (a / rel).read_bytes() == (b / rel).read_bytes(), rel


def test_build_removes_stale_addon_files(mini_addons: Path, tmp_path: Path):
    out = tmp_path / "out"
    stale = out / "mini" / "estado" / "antiga.bmd"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")
    build(mini_addons, out)
    assert not stale.exists()


def test_index_toml_contents(mini_addons: Path, tmp_path: Path):
    out = tmp_path / "out"
    build(mini_addons, out)
    index = tomllib.loads((out / "index.toml").read_text(encoding="utf-8"))
    assert index["spec_version"] == 0
    assert index["addons"] == [{"id": "mini", "version": "1.2.3", "manifest": "mini/manifest.toml"}]
    props = {p["id"]: p for p in index["properties"]}
    pop = props["mini/estado/pop"]
    assert pop["file"] == "mini/estado/pop.bmd"
    assert (out / pop["file"]).is_file()
    assert pop["rows"] == 5
    assert pop["period_min"] == "2000-02-29"
    assert pop["period_max"] == "2023-12-31"
    assert pop["period_min_days"] == days_since_epoch(date(2000, 2, 29))
    assert pop["period_max_days"] == days_since_epoch(date(2023, 12, 31))
    assert pop["name"] == "População"
    assert pop["unit"] == "habitantes"
    assert pop["dtype"] == "i64"
    assert pop["entity_type"] == "estado"
    assert pop["addon"] == "mini"
    assert pop["periodicity"] == "anual"
    assert props["mini/estado/area"]["unit"] == "km²"
    vazia = props["mini/pais/vazia"]
    assert vazia["rows"] == 0 and "period_min" not in vazia and "period_max" not in vazia


def test_build_aborts_on_validation_errors(fixture_addons_dir, tmp_path: Path):
    out = tmp_path / "out"
    with pytest.raises(BuildError) as exc:
        build(fixture_addons_dir("dup_csv_key"), out)
    assert any(f.level == "ERROR" for f in exc.value.findings)
    assert not out.exists()


# -- CLI --------------------------------------------------------------------


def test_cli_build_and_inspect(mini_addons: Path, tmp_path: Path, capsys):
    out = tmp_path / "out"
    assert main(["build", str(mini_addons), "--out", str(out)]) == 0
    stdout = capsys.readouterr().out
    assert "mini/estado/pop: 5 rows, 2000-02-29..2023-12-31 -> mini/estado/pop.bmd" in stdout
    assert "OK:" in stdout

    assert main(["inspect", str(out / "mini" / "estado" / "pop.bmd")]) == 0
    stdout = capsys.readouterr().out
    assert "dtype:         i64" in stdout
    assert "row_count:     5" in stdout
    assert "entity_count:  3" in stdout
    assert "2022-01-01" in stdout and "2022-12-31" in stdout
    assert "10882965" in stdout

    assert main(["inspect", str(out / "mini" / "estado" / "capital.bmd"), "-n", "2"]) == 0
    stdout = capsys.readouterr().out
    assert "string_count:  6" in stdout
    assert "rows (2 of 6)" in stdout


def test_cli_build_failure_exit_code(fixture_addons_dir, tmp_path: Path, capsys):
    out = tmp_path / "out"
    assert main(["build", str(fixture_addons_dir("dup_csv_key")), "--out", str(out)]) == 1
    captured = capsys.readouterr()
    assert "ERROR dup-key:" in captured.out
    assert "FAILED" in captured.err
    assert not out.exists()


def test_cli_inspect_rejects_garbage(tmp_path: Path, capsys):
    bad = tmp_path / "bad.bmd"
    bad.write_bytes(b"NOPE" + b"\0" * 20)
    assert main(["inspect", str(bad)]) == 1
    assert "bad magic" in capsys.readouterr().err


# -- the real addon -----------------------------------------------------------


def test_build_real_addons(real_addons_dir: Path, tmp_path: Path):
    out = tmp_path / "out"
    result = build(real_addons_dir, out)
    by_id = {p.id: p for p in result.properties}
    assert set(by_id) == {
        "ibge-core/estado/populacao",
        "ibge-core/estado/pib",
        "ibge-core/estado/area_km2",
        "ibge-core/pais/populacao",
        "ibge-core/pais/pib",
    }
    pop = read_bmd(out / "ibge-core" / "estado" / "populacao.bmd")
    assert len(pop["entities"]) == 27
    assert pop["idx"] == sorted(pop["idx"])
    # Censo 2022 row for Rio Grande do Sul survived the merge with the estimates.
    rs = pop["entities"].index("estado:43")
    row = [(s, v) for i, s, v in zip(pop["idx"], pop["starts"], pop["values"]) if i == rs and s == 18993]
    assert row == [(18993, 10882965)]
    assert by_id["ibge-core/estado/area_km2"].rows == 27
    assert by_id["ibge-core/pais/pib"].rows >= 22
