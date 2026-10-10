"""Validator behaviour on the real addons and on the broken fixtures."""

from __future__ import annotations

from datetime import date

import pytest

from bramapa_data.validate import check_value, has_errors, parse_period, validate


def errors(findings):
    return [f for f in findings if f.level == "ERROR"]


def test_real_addons_validate_clean(real_addons_dir):
    findings = validate(real_addons_dir)
    assert findings == [], "\n".join(str(f) for f in findings)


def test_template_directory_is_skipped(real_addons_dir):
    # _template has a property pointing at a header-only CSV, which would WARN
    # ("no data rows") if it were validated.
    assert (real_addons_dir / "_template" / "manifest.toml").is_file()
    assert not any("_template" in str(f) or "meu-addon" in f.addon for f in validate(real_addons_dir))


def test_duplicate_property_id_fails(fixture_addons_dir):
    findings = validate(fixture_addons_dir("dup_property"))
    assert has_errors(findings)
    assert any("duplicate property id" in f.message and f.addon == "dup-prop" for f in errors(findings))


def test_unknown_entity_type_fails(fixture_addons_dir):
    findings = validate(fixture_addons_dir("unknown_entity_type"))
    assert has_errors(findings)
    assert any("unknown entity_type 'bairro'" in f.message and f.addon == "bad-type" for f in errors(findings))


def test_duplicate_csv_key_fails(fixture_addons_dir):
    findings = validate(fixture_addons_dir("dup_csv_key"))
    assert has_errors(findings)
    dup = [f for f in errors(findings) if "duplicate key" in f.message]
    assert len(dup) == 1
    # Empty period_end is normalised to period_start before keying, so line 4
    # collides with line 2.
    assert "estado_populacao.csv:4" in dup[0].message
    assert "first at line 2" in dup[0].message


def test_circular_depends_fails(fixture_addons_dir):
    findings = validate(fixture_addons_dir("circular_depends"))
    assert has_errors(findings)
    cyc = [f for f in errors(findings) if "circular depends" in f.message]
    assert len(cyc) == 1, [str(f) for f in findings]
    assert "ring-a -> ring-b -> ring-a" in cyc[0].message
    # Cross-addon entity type resolution itself works: the only error is the cycle.
    assert errors(findings) == cyc


def test_missing_directory_is_an_error(tmp_path):
    findings = validate(tmp_path / "nope")
    assert has_errors(findings)


def test_empty_directory_only_warns(tmp_path):
    findings = validate(tmp_path)
    assert not has_errors(findings)
    assert any(f.level == "WARN" for f in findings)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("2022", (date(2022, 1, 1), date(2022, 12, 31))),
        ("2022-02", (date(2022, 2, 1), date(2022, 2, 28))),
        ("2024-02", (date(2024, 2, 1), date(2024, 2, 29))),
        ("2022-12", (date(2022, 12, 1), date(2022, 12, 31))),
        ("2022-07-15", (date(2022, 7, 15), date(2022, 7, 15))),
        ("2022-13", None),
        ("2022-02-30", None),
        ("22", None),
        ("2022/01", None),
        ("", None),
    ],
)
def test_parse_period(text, expected):
    assert parse_period(text) == expected


@pytest.mark.parametrize(
    "text,dtype,ok",
    [
        ("123", "i64", True),
        ("-7", "i64", True),
        ("1.0", "i64", False),
        ("9223372036854775808", "i64", False),
        ("1.5", "f64", True),
        ("1e6", "f64", True),
        (".5", "f64", True),
        ("1,5", "f64", False),
        ("nan", "f64", False),
        ("anything", "str", True),
    ],
)
def test_check_value(text, dtype, ok):
    assert (check_value(text, dtype) is None) is ok
