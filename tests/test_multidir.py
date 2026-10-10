"""Several addon roots validated and built as one set (Fase 5: community addons in their own repos)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from bramapa_data.build import BuildError, build
from bramapa_data.cli import main
from bramapa_data.validate import has_errors, load_addons, validate

CSV = "entity,period_start,period_end,value\nestado:43,2022,2022,{value}\n"


def manifest(addon_id: str, prop: str = "x", entity_type: str = "estado", depends: str = "", extra: str = "") -> str:
    return f"""spec_version = 0

[addon]
id = "{addon_id}"
name = "{addon_id}"
version = "0.1.0"
license = "CC0-1.0"
depends = [{depends}]
{extra}
[[properties]]
id = "{prop}"
entity_type = "{entity_type}"
name = "{prop}"
unit = "u"
dtype = "i64"
periodicity = "anual"
source = "test"
file = "data/{prop}.csv"
"""


def make_addon(root: Path, addon_id: str, dirname: str | None = None, **kw) -> Path:
    path = root / (dirname or addon_id)
    (path / "data").mkdir(parents=True)
    (path / "manifest.toml").write_text(manifest(addon_id, **kw), encoding="utf-8")
    prop = kw.get("prop", "x")
    rows = CSV.format(value=1)
    if kw.get("entity_type", "estado") not in ("estado", "pais", "municipio"):
        rows = "entity,period_start,period_end,value\ntorre:1,2022,2022,1\n"
    (path / "data" / f"{prop}.csv").write_text(rows, encoding="utf-8")
    return path


@pytest.fixture
def two_roots(tmp_path: Path) -> tuple[Path, Path]:
    a = tmp_path / "repo-a" / "addons"
    b = tmp_path / "repo-b" / "addons"
    make_addon(a, "alpha", prop="pop")
    make_addon(b, "beta", prop="area")
    return a, b


def test_load_addons_concatenates_roots(two_roots):
    a, b = two_roots
    assert [ad.id for ad in load_addons([a, b])] == ["alpha", "beta"]
    assert [ad.id for ad in load_addons(a)] == ["alpha"]  # single Path still works
    assert [ad.id for ad in load_addons(str(a))] == ["alpha"]


def test_validate_two_roots_clean(two_roots):
    a, b = two_roots
    assert validate([a, b]) == []
    assert validate((str(a), str(b))) == []


def test_duplicate_id_across_roots_is_an_error(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    make_addon(a, "energia")
    make_addon(b, "energia")
    assert validate(a) == []
    assert validate(b) == []
    findings = validate([a, b])
    assert has_errors(findings)
    dup = [f for f in findings if f.level == "ERROR" and "is also declared by" in f.message]
    assert len(dup) == 1
    assert dup[0].addon == "energia"
    assert str(a) in dup[0].message  # names the other root, since the dirnames are equal


def test_depends_resolves_across_roots(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    base = make_addon(a, "base")
    (base / "manifest.toml").write_text(
        manifest("base")
        + '\n[[entity_types]]\nid = "torre"\nname = "Torre"\nmin_level = 2\nposition = "none"\nfile = "data/torre.csv"\n',
        encoding="utf-8",
    )
    (base / "data" / "torre.csv").write_text("entity,name\ntorre:1,Torre Um\n", encoding="utf-8")
    make_addon(b, "ext", prop="altura", entity_type="base/torre", depends='"base"')

    alone = validate(b)
    assert has_errors(alone)
    assert any("depends on 'base', which is not present" in f.message for f in alone)

    together = validate([a, b])
    assert together == [], "\n".join(str(f) for f in together)


def test_missing_root_is_an_error_even_with_a_good_one(two_roots, tmp_path: Path):
    a, _ = two_roots
    findings = validate([a, tmp_path / "nope"])
    assert has_errors(findings)
    assert any("directory not found" in f.message and "nope" in f.message for f in findings)


def test_build_two_roots_into_one_tree(two_roots, tmp_path: Path):
    a, b = two_roots
    out = tmp_path / "out"
    result = build([a, b], out)
    assert [ad.id for ad in result.addons] == ["alpha", "beta"]
    assert sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()) == [
        "alpha/estado/pop.bmd",
        "alpha/manifest.toml",
        "beta/estado/area.bmd",
        "beta/manifest.toml",
        "index.toml",
    ]
    index = tomllib.loads((out / "index.toml").read_text(encoding="utf-8"))
    assert [p["id"] for p in index["properties"]] == ["alpha/estado/pop", "beta/estado/area"]


def test_build_two_roots_duplicate_id_aborts(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    make_addon(a, "same")
    make_addon(b, "same")
    out = tmp_path / "out"
    with pytest.raises(BuildError):
        build([a, b], out)
    assert not out.exists()


def test_cli_accepts_several_roots(two_roots, tmp_path: Path, capsys):
    a, b = two_roots
    assert main(["validate", str(a), str(b)]) == 0
    assert capsys.readouterr().out.startswith("OK: 2 addon(s)")

    assert main(["list", str(a), str(b)]) == 0
    out = capsys.readouterr().out
    assert "alpha/estado/pop" in out and "beta/estado/area" in out

    target = tmp_path / "built"
    assert main(["build", str(a), str(b), "--out", str(target)]) == 0
    assert (target / "alpha" / "estado" / "pop.bmd").is_file()
    assert (target / "beta" / "estado" / "area.bmd").is_file()


def test_cli_duplicate_across_roots_fails(tmp_path: Path, capsys):
    a = tmp_path / "a"
    b = tmp_path / "b"
    make_addon(a, "same")
    make_addon(b, "same")
    assert main(["validate", str(a), str(b)]) == 1
    captured = capsys.readouterr()
    assert "ERROR same:" in captured.out
    assert "FAILED" in captured.err
