"""Build ``.bmd`` files and ``index.toml`` from validated addons.

Output tree (``docs/spec/data-binary.md``)::

    OUT/<addon-id>/<entity_type>/<property-id>.bmd
    OUT/<addon-id>/manifest.toml      # byte-for-byte copy
    OUT/index.toml

Validation runs first and any ``ERROR`` aborts the build (:class:`BuildError`).
The output is deterministic: same addons in → same bytes out. Each addon's
output directory is removed and recreated so stale files never linger.
"""

from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .bmd import Row, date_from_days, days_since_epoch, encode
from .validate import Finding, has_errors, load_addons, parse_period, validate


class BuildError(Exception):
    """Validation found errors; nothing was written."""

    def __init__(self, findings: list[Finding]):
        super().__init__(f"{sum(1 for f in findings if f.level == 'ERROR')} validation error(s)")
        self.findings = findings


@dataclass(frozen=True)
class BuiltProperty:
    addon: str
    entity_type: str
    prop_id: str
    name: str
    unit: str
    dtype: str
    periodicity: str
    file: str  # relative to the output directory, POSIX separators
    rows: int
    period_min: int | None  # days since epoch; None when the property has no rows
    period_max: int | None

    @property
    def id(self) -> str:
        return f"{self.addon}/{self.entity_type}/{self.prop_id}"


@dataclass(frozen=True)
class BuiltAddon:
    id: str
    version: str
    manifest: str  # relative path of the manifest copy


@dataclass
class BuildResult:
    out_dir: Path
    findings: list[Finding]
    addons: list[BuiltAddon]
    properties: list[BuiltProperty]


def read_property_rows(path: Path, dtype: str) -> list[Row]:
    """Load a validated property CSV as :class:`Row` values.

    Blank lines and rows with an empty ``value`` are skipped, matching the
    validator. Anything else is assumed well-formed (the build validates first).
    """
    text = path.read_text(encoding="utf-8", newline="")
    if text.startswith("﻿"):
        text = text[1:]
    reader = csv.reader(text.splitlines())
    next(reader, None)  # header, already validated
    rows: list[Row] = []
    for raw in reader:
        if not raw or all(not c.strip() for c in raw):
            continue
        entity, start_s, end_s, value_s = (c.strip() for c in raw)
        if value_s == "":
            continue
        start = parse_period(start_s)
        end = parse_period(end_s) if end_s else start
        assert start is not None and end is not None, f"{path}: unvalidated period {start_s!r}/{end_s!r}"
        value: int | float | str
        if dtype == "i64":
            value = int(value_s)
        elif dtype == "f64":
            value = float(value_s)
        else:
            value = value_s
        rows.append(Row(entity, days_since_epoch(start[0]), days_since_epoch(end[1]), value))
    return rows


def build(addons_dir: Path | str, out_dir: Path | str) -> BuildResult:
    """Validate ``addons_dir`` and write the binary tree under ``out_dir``."""
    addons_dir = Path(addons_dir)
    out_dir = Path(out_dir)
    findings = validate(addons_dir)
    if has_errors(findings):
        raise BuildError(findings)

    out_dir.mkdir(parents=True, exist_ok=True)
    built_addons: list[BuiltAddon] = []
    built_props: list[BuiltProperty] = []

    for addon in sorted(load_addons(addons_dir), key=lambda a: a.label):
        assert addon.manifest is not None and addon.id is not None  # validated
        addon_out = out_dir / addon.id
        if addon_out.exists():
            shutil.rmtree(addon_out)
        addon_out.mkdir(parents=True)
        shutil.copyfile(addon.path / "manifest.toml", addon_out / "manifest.toml")
        built_addons.append(BuiltAddon(addon.id, addon.manifest["addon"]["version"], f"{addon.id}/manifest.toml"))

        for prop in addon.properties:
            entity_type: str = prop["entity_type"]
            # Dependency-prefixed types ("other-addon/usina") become a plain
            # directory name; the engine resolves types from the manifest.
            type_dir = entity_type.rsplit("/", 1)[-1]
            dtype: str = prop["dtype"]
            rows = read_property_rows(addon.path / prop["file"], dtype)
            rel = f"{addon.id}/{type_dir}/{prop['id']}.bmd"
            target = out_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(encode(rows, dtype))
            built_props.append(
                BuiltProperty(
                    addon=addon.id,
                    entity_type=entity_type,
                    prop_id=prop["id"],
                    name=prop["name"],
                    unit=prop["unit"],
                    dtype=dtype,
                    periodicity=prop["periodicity"],
                    file=rel,
                    rows=len(rows),
                    period_min=min((r.period_start for r in rows), default=None),
                    period_max=max((r.period_end for r in rows), default=None),
                )
            )

    (out_dir / "index.toml").write_text(render_index(built_addons, built_props), encoding="utf-8")
    return BuildResult(out_dir, findings, built_addons, built_props)


def _toml_str(value: str) -> str:
    """Quote ``value`` as a TOML basic string."""
    out = ['"']
    for ch in value:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20 or ch == "\x7f":
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def render_index(addons: list[BuiltAddon], properties: list[BuiltProperty]) -> str:
    """Render ``index.toml``: the spec's fields plus name/unit/dtype/entity_type/addon.

    ``period_min``/``period_max`` are full ISO dates (``YYYY-MM-DD``) of the
    earliest ``period_start`` and latest ``period_end``; ``period_min_days`` /
    ``period_max_days`` carry the same values as days since 1970-01-01. Both
    are omitted for a property with zero rows.
    """
    lines = [
        "# Generated by bramapa-data build; do not edit.",
        "spec_version = 0",
        f"generator = {_toml_str(f'bramapa-data {__version__}')}",
        "",
    ]
    for addon in addons:
        lines += [
            "[[addons]]",
            f"id = {_toml_str(addon.id)}",
            f"version = {_toml_str(addon.version)}",
            f"manifest = {_toml_str(addon.manifest)}",
            "",
        ]
    for prop in properties:
        lines += [
            "[[properties]]",
            f"id = {_toml_str(prop.id)}",
            f"file = {_toml_str(prop.file)}",
            f"rows = {prop.rows}",
        ]
        if prop.period_min is not None and prop.period_max is not None:
            lines += [
                f"period_min = {_toml_str(date_from_days(prop.period_min).isoformat())}",
                f"period_max = {_toml_str(date_from_days(prop.period_max).isoformat())}",
                f"period_min_days = {prop.period_min}",
                f"period_max_days = {prop.period_max}",
            ]
        lines += [
            f"addon = {_toml_str(prop.addon)}",
            f"entity_type = {_toml_str(prop.entity_type)}",
            f"name = {_toml_str(prop.name)}",
            f"unit = {_toml_str(prop.unit)}",
            f"dtype = {_toml_str(prop.dtype)}",
            f"periodicity = {_toml_str(prop.periodicity)}",
            "",
        ]
    return "\n".join(lines)
