"""CLI exit codes and output shape."""

from bramapa_data.cli import main


def test_validate_real_addons_exit_zero(real_addons_dir, capsys):
    assert main(["validate", str(real_addons_dir)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("OK:")


def test_validate_broken_fixture_exit_nonzero(fixture_addons_dir, capsys):
    assert main(["validate", str(fixture_addons_dir("dup_csv_key"))]) == 1
    captured = capsys.readouterr()
    assert "ERROR dup-key:" in captured.out
    assert "FAILED" in captured.err


def test_list_shows_canonical_property_ids(real_addons_dir, capsys):
    assert main(["list", str(real_addons_dir)]) == 0
    out = capsys.readouterr().out
    for prop in (
        "ibge-core/estado/populacao",
        "ibge-core/estado/pib",
        "ibge-core/estado/area_km2",
        "ibge-core/pais/populacao",
        "ibge-core/pais/pib",
    ):
        assert prop in out
    assert "meu-addon" not in out
