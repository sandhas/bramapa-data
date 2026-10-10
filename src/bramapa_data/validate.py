"""Validator for Bramapa data addons (spec v0).

Implements the eight rejection rules from ``docs/spec/addon.md``:

1. unknown ``spec_version``;
2. invalid or duplicated ``addon.id`` across addons;
3. duplicated property / entity type ids inside an addon;
4. ``entity_type`` that is neither base, nor declared, nor provided by a
   dependency;
5. referenced file missing, CSV without the required columns, ``value``
   not matching ``dtype``;
6. duplicated ``(entity, period_start, period_end)`` key;
7. ``render.property`` / ``map_overrides.path`` pointing at nothing;
8. circular ``depends``.

Findings are plain records (``ERROR``/``WARN``); the CLI decides how to
print them and what exit code to use.
"""

from __future__ import annotations

import csv
import re
import tomllib
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

KNOWN_SPEC_VERSIONS = {0}

BASE_ENTITY_TYPES = ("pais", "estado", "municipio")
BASE_ENTITY_CODE_RE = {
    "pais": re.compile(r"^[A-Z]{2}$"),  # ISO 3166-1 alpha-2
    "estado": re.compile(r"^\d{2}$"),  # IBGE UF code
    "municipio": re.compile(r"^\d{7}$"),  # IBGE municipality code
}

ADDON_ID_RE = re.compile(r"^[a-z0-9-]+$")
LOCAL_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")  # entity type ids and property ids
ENTITY_RE = re.compile(r"^([a-z][a-z0-9_-]*):(\S+)$")
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
PERIOD_RE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")
I64_RE = re.compile(r"^[+-]?\d+$")
F64_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")
I64_MIN, I64_MAX = -(2**63), 2**63 - 1

DTYPES = ("i64", "f64", "str")
PERIODICITIES = ("anual", "decenal", "mensal", "diaria", "pontual")
RENDER_KINDS = ("choropleth", "icon", "label")
SCALES = ("linear", "log")
POSITIONS = ("latlon", "none")

PROPERTY_CSV_HEADER = ["entity", "period_start", "period_end", "value"]
ENTITY_CSV_HEADER_PREFIX = ["entity", "name"]

MAX_ROW_FINDINGS_PER_FILE = 20

ADDON_KEYS = {"id", "name", "version", "license", "authors", "description", "depends"}
ENTITY_TYPE_KEYS = {"id", "name", "min_level", "position", "icon", "file"}
PROPERTY_KEYS = {
    "id", "entity_type", "name", "unit", "dtype", "periodicity",
    "source", "source_url", "license", "file",
}
RENDER_KEYS = {"property", "kind", "ramp", "scale"}
MAP_OVERRIDE_KEYS = {"level", "entity", "path", "chunks", "priority"}
TOP_LEVEL_KEYS = {"spec_version", "addon", "entity_types", "properties", "render", "map_overrides"}


@dataclass(frozen=True)
class Finding:
    level: str  # "ERROR" | "WARN"
    addon: str  # addon id, or directory name when the id is unknown
    message: str

    def __str__(self) -> str:
        return f"{self.level} {self.addon}: {self.message}"


@dataclass
class Addon:
    """An addon directory with its parsed (but not yet validated) manifest."""

    path: Path
    manifest: dict[str, Any] | None
    load_error: str | None = None

    @property
    def dirname(self) -> str:
        return self.path.name

    @property
    def id(self) -> str | None:
        if not self.manifest:
            return None
        addon = self.manifest.get("addon")
        if isinstance(addon, dict) and isinstance(addon.get("id"), str):
            return addon["id"]
        return None

    @property
    def label(self) -> str:
        return self.id or self.dirname

    def _tables(self, key: str) -> list[dict[str, Any]]:
        if not self.manifest:
            return []
        value = self.manifest.get(key, [])
        if not isinstance(value, list):
            return []
        return [t for t in value if isinstance(t, dict)]

    @property
    def depends(self) -> list[str]:
        if not self.manifest:
            return []
        addon = self.manifest.get("addon")
        if not isinstance(addon, dict):
            return []
        deps = addon.get("depends", [])
        if not isinstance(deps, list):
            return []
        return [d for d in deps if isinstance(d, str)]

    @property
    def entity_types(self) -> list[dict[str, Any]]:
        return self._tables("entity_types")

    @property
    def entity_type_ids(self) -> set[str]:
        return {t["id"] for t in self.entity_types if isinstance(t.get("id"), str)}

    @property
    def properties(self) -> list[dict[str, Any]]:
        return self._tables("properties")

    @property
    def renders(self) -> list[dict[str, Any]]:
        return self._tables("render")

    @property
    def map_overrides(self) -> list[dict[str, Any]]:
        return self._tables("map_overrides")

    def local_property_ids(self) -> list[str]:
        """``<entity_type>/<id>`` for every property, in manifest order."""
        out = []
        for prop in self.properties:
            et, pid = prop.get("entity_type"), prop.get("id")
            if isinstance(et, str) and isinstance(pid, str):
                out.append(f"{et}/{pid}")
        return out

    def canonical_property_ids(self) -> list[str]:
        """``<addon>/<entity_type>/<id>`` for every property."""
        return [f"{self.label}/{p}" for p in self.local_property_ids()]


def parse_period(text: str) -> tuple[date, date] | None:
    """Parse ``YYYY``, ``YYYY-MM`` or ``YYYY-MM-DD`` into an inclusive day range.

    Returns ``None`` when the text is not a valid ISO 8601 date of one of
    those three shapes (e.g. ``2022-13``).
    """
    m = PERIOD_RE.match(text)
    if not m:
        return None
    year_s, month_s, day_s = m.groups()
    try:
        year = int(year_s)
        if month_s is None:
            return date(year, 1, 1), date(year, 12, 31)
        month = int(month_s)
        if day_s is None:
            start = date(year, month, 1)
            if month == 12:
                end = date(year + 1, 1, 1) - timedelta(days=1)
            else:
                end = date(year, month + 1, 1) - timedelta(days=1)
            return start, end
        day = date(year, month, int(day_s))
        return day, day
    except ValueError:
        return None


def check_value(text: str, dtype: str) -> str | None:
    """Return an error message if ``text`` is not a valid ``dtype`` value."""
    if dtype == "i64":
        if not I64_RE.match(text):
            return f"'{text}' is not an integer"
        if not I64_MIN <= int(text) <= I64_MAX:
            return f"'{text}' is out of i64 range"
    elif dtype == "f64":
        if not F64_RE.match(text):
            return f"'{text}' is not a decimal number"
    elif dtype == "str":
        return None
    else:
        return f"unknown dtype '{dtype}'"
    return None


AddonsDirs = Path | str | Iterable[Path | str]


def as_dirs(addons_dirs: AddonsDirs) -> list[Path]:
    """Normalise one directory or a sequence of directories to a list of paths."""
    if isinstance(addons_dirs, (Path, str)):
        return [Path(addons_dirs)]
    return [Path(d) for d in addons_dirs]


def load_addons(addons_dirs: AddonsDirs) -> list[Addon]:
    """Discover addon directories under one or more roots and parse their manifests.

    Directories whose name starts with ``_`` (templates) or ``.`` are skipped,
    and so are roots that do not exist (the validator reports those). Parse
    failures are recorded in ``Addon.load_error`` instead of raising. With
    several roots the result is their concatenation, in the order given.
    """
    addons: list[Addon] = []
    for addons_dir in as_dirs(addons_dirs):
        addons.extend(_load_addons_from(addons_dir))
    return addons


def _load_addons_from(addons_dir: Path) -> list[Addon]:
    addons: list[Addon] = []
    if not addons_dir.is_dir():
        return addons
    for path in sorted(addons_dir.iterdir()):
        if not path.is_dir() or path.name.startswith(("_", ".")):
            continue
        manifest_path = path / "manifest.toml"
        if not manifest_path.is_file():
            addons.append(Addon(path, None, "manifest.toml not found"))
            continue
        try:
            with manifest_path.open("rb") as fh:
                manifest = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            addons.append(Addon(path, None, f"manifest.toml: invalid TOML: {exc}"))
            continue
        except OSError as exc:
            addons.append(Addon(path, None, f"manifest.toml: {exc}"))
            continue
        addons.append(Addon(path, manifest))
    return addons


class Validator:
    """Validates every addon under one or more ``addons_dirs`` as a single set.

    Addons from all roots share one namespace: ``addon.id`` must be unique
    across roots and ``depends`` may point at an addon in any root.
    """

    def __init__(self, addons_dirs: AddonsDirs):
        self.addons_dirs = as_dirs(addons_dirs)
        self.findings: list[Finding] = []
        self.by_id: dict[str, Addon] = {}

    # -- reporting -----------------------------------------------------------

    def error(self, addon: Addon | str, message: str) -> None:
        label = addon if isinstance(addon, str) else addon.label
        self.findings.append(Finding("ERROR", label, message))

    def warn(self, addon: Addon | str, message: str) -> None:
        label = addon if isinstance(addon, str) else addon.label
        self.findings.append(Finding("WARN", label, message))

    @property
    def has_errors(self) -> bool:
        return any(f.level == "ERROR" for f in self.findings)

    @property
    def dirs_label(self) -> str:
        return ", ".join(str(d) for d in self.addons_dirs)

    # -- entry point ---------------------------------------------------------

    def run(self) -> list[Finding]:
        for addons_dir in self.addons_dirs:
            if not addons_dir.is_dir():
                self.error("addons", f"directory not found: {addons_dir}")
        if self.has_errors:
            return self.findings

        addons = load_addons(self.addons_dirs)
        if not addons:
            self.warn("addons", f"no addons found under {self.dirs_label}")
            return self.findings

        loaded: list[Addon] = []
        for addon in addons:
            if addon.load_error:
                self.error(addon, addon.load_error)
                continue
            if self._check_manifest_shape(addon):
                loaded.append(addon)

        self._check_unique_ids(loaded)
        self._check_depends(loaded)

        for addon in loaded:
            self._check_entity_types(addon)
            self._check_properties(addon)
            self._check_render(addon)
            self._check_map_overrides(addon)
            self._check_unreferenced_files(addon)
        return self.findings

    # -- helpers -------------------------------------------------------------

    def _field(
        self,
        addon: Addon,
        table: dict[str, Any],
        key: str,
        types: type | tuple[type, ...],
        where: str,
        required: bool = True,
    ) -> Any:
        """Fetch ``table[key]`` checking its type; report and return None otherwise."""
        if key not in table:
            if required:
                self.error(addon, f"{where}: missing required field '{key}'")
            return None
        value = table[key]
        # bool is a subclass of int in Python; TOML booleans must not pass as ints.
        if isinstance(value, bool) and bool not in (types if isinstance(types, tuple) else (types,)):
            self.error(addon, f"{where}: field '{key}' has wrong type (expected {_type_name(types)})")
            return None
        if not isinstance(value, types):
            self.error(addon, f"{where}: field '{key}' has wrong type (expected {_type_name(types)})")
            return None
        return value

    def _unknown_keys(self, addon: Addon, table: dict[str, Any], allowed: set[str], where: str) -> None:
        for key in sorted(set(table) - allowed):
            self.warn(addon, f"{where}: unknown field '{key}' (typo?)")

    def _resolve_entity_type(self, addon: Addon, entity_type: str, where: str) -> str | None:
        """Resolve an ``entity_type`` reference to its local type name.

        Base types and the addon's own declared types are unprefixed. Types
        from a dependency are written ``<dep-addon>/<type>``. Returns the local
        type name (the prefix used in entity ids) or None after reporting.
        """
        if "/" in entity_type:
            dep, _, local = entity_type.partition("/")
            if dep == addon.id:
                # Self-prefixed own type: accepted, but the spec writes own types bare.
                if local in addon.entity_type_ids:
                    return local
                self.error(addon, f"{where}: entity_type '{entity_type}' is not declared by this addon")
                return None
            if dep not in addon.depends:
                self.error(
                    addon,
                    f"{where}: entity_type '{entity_type}' references addon '{dep}', "
                    f"which is not listed in addon.depends",
                )
                return None
            dep_addon = self.by_id.get(dep)
            if dep_addon is None:
                self.error(addon, f"{where}: entity_type '{entity_type}' references unknown addon '{dep}'")
                return None
            if local not in dep_addon.entity_type_ids:
                self.error(addon, f"{where}: entity_type '{entity_type}' is not declared by addon '{dep}'")
                return None
            return local
        if entity_type in BASE_ENTITY_TYPES or entity_type in addon.entity_type_ids:
            return entity_type
        self.error(
            addon,
            f"{where}: unknown entity_type '{entity_type}' "
            f"(not a base type {list(BASE_ENTITY_TYPES)}, not declared, not from a dependency)",
        )
        return None

    def _check_entity_id(self, addon: Addon, entity: str, expected_type: str | None, where: str) -> bool:
        m = ENTITY_RE.match(entity)
        if not m:
            self.error(addon, f"{where}: entity '{entity}' is not in the form <tipo>:<codigo>")
            return False
        etype, code = m.groups()
        if expected_type is not None and etype != expected_type:
            self.error(addon, f"{where}: entity '{entity}' has type '{etype}', expected '{expected_type}'")
            return False
        code_re = BASE_ENTITY_CODE_RE.get(etype)
        if code_re and not code_re.match(code):
            self.error(addon, f"{where}: entity '{entity}' has an invalid code for base type '{etype}'")
            return False
        return True

    def _open_csv(self, addon: Addon, path: Path, where: str):
        try:
            text = path.read_text(encoding="utf-8", newline="")
        except UnicodeDecodeError as exc:
            self.error(addon, f"{where}: not valid UTF-8 ({exc.reason} at byte {exc.start})")
            return None
        except OSError as exc:
            self.error(addon, f"{where}: {exc}")
            return None
        if text.startswith("﻿"):
            self.warn(addon, f"{where}: UTF-8 BOM found and ignored; please save without BOM")
            text = text[1:]
        return list(csv.reader(text.splitlines()))

    # -- rule 1 + manifest shape --------------------------------------------

    def _check_manifest_shape(self, addon: Addon) -> bool:
        """Rule 1 plus the basic shape of ``[addon]``. Returns False if unusable."""
        manifest = addon.manifest
        assert manifest is not None
        ok = True

        self._unknown_keys(addon, manifest, TOP_LEVEL_KEYS, "manifest.toml")

        if "spec_version" not in manifest:
            self.error(addon, "manifest.toml: missing 'spec_version'")
            ok = False
        else:
            sv = manifest["spec_version"]
            if isinstance(sv, bool) or not isinstance(sv, int) or sv not in KNOWN_SPEC_VERSIONS:
                self.error(
                    addon,
                    f"manifest.toml: unknown spec_version {sv!r} (known: {sorted(KNOWN_SPEC_VERSIONS)})",
                )
                ok = False

        table = manifest.get("addon")
        if not isinstance(table, dict):
            self.error(addon, "manifest.toml: missing [addon] table")
            return False
        self._unknown_keys(addon, table, ADDON_KEYS, "[addon]")

        addon_id = self._field(addon, table, "id", str, "[addon]")
        if addon_id is None:
            ok = False
        elif not ADDON_ID_RE.match(addon_id):
            self.error(addon, f"[addon]: invalid id '{addon_id}' (must match [a-z0-9-]+)")
            ok = False
        elif addon_id != addon.dirname:
            self.warn(addon, f"[addon]: id '{addon_id}' differs from directory name '{addon.dirname}'")

        self._field(addon, table, "name", str, "[addon]")
        version = self._field(addon, table, "version", str, "[addon]")
        if version is not None and not SEMVER_RE.match(version):
            self.error(addon, f"[addon]: version '{version}' is not semver (MAJOR.MINOR.PATCH)")
        self._field(addon, table, "license", str, "[addon]")
        authors = self._field(addon, table, "authors", list, "[addon]", required=False)
        if authors is not None and not all(isinstance(a, str) for a in authors):
            self.error(addon, "[addon]: 'authors' must be a list of strings")
        self._field(addon, table, "description", str, "[addon]", required=False)
        depends = self._field(addon, table, "depends", list, "[addon]", required=False)
        if depends is not None:
            for dep in depends:
                if not isinstance(dep, str) or not ADDON_ID_RE.match(dep):
                    self.error(addon, f"[addon]: invalid entry in depends: {dep!r}")

        for key in ("entity_types", "properties", "render", "map_overrides"):
            if key in manifest and not (
                isinstance(manifest[key], list) and all(isinstance(t, dict) for t in manifest[key])
            ):
                self.error(addon, f"manifest.toml: '{key}' must be an array of tables ([[{key}]])")

        if not addon.properties and not addon.entity_types and not addon.map_overrides:
            self.warn(addon, "manifest declares no properties, entity types or map overrides")
        return ok

    # -- rule 2 --------------------------------------------------------------

    def _check_unique_ids(self, addons: list[Addon]) -> None:
        seen: dict[str, Addon] = {}
        for addon in addons:
            if addon.id is None:
                continue
            if addon.id in seen:
                other = seen[addon.id]
                where = f"directory '{other.dirname}'"
                if other.path.parent != addon.path.parent:
                    where += f" under {other.path.parent}"
                self.error(addon, f"[addon]: id '{addon.id}' is also declared by {where}")
                continue
            seen[addon.id] = addon
        self.by_id = seen

    # -- rule 8 --------------------------------------------------------------

    def _check_depends(self, addons: list[Addon]) -> None:
        for addon in addons:
            for dep in addon.depends:
                if dep not in self.by_id:
                    self.error(addon, f"[addon]: depends on '{dep}', which is not present under {self.dirs_label}")

        reported: set[frozenset[str]] = set()
        for start in sorted(self.by_id):
            cycle = _find_cycle(start, self.by_id)
            if cycle and frozenset(cycle) not in reported:
                reported.add(frozenset(cycle))
                self.error(cycle[0], "circular depends: " + " -> ".join(cycle + [cycle[0]]))

    # -- rule 3 (entity types) + rule 5 (entity files) -----------------------

    def _check_entity_types(self, addon: Addon) -> None:
        seen: dict[str, int] = {}
        for i, table in enumerate(addon.entity_types):
            where = f"[[entity_types]] #{i + 1}"
            self._unknown_keys(addon, table, ENTITY_TYPE_KEYS, where)
            type_id = self._field(addon, table, "id", str, where)
            if type_id is not None:
                where = f"[[entity_types]] '{type_id}'"
                if not LOCAL_ID_RE.match(type_id):
                    self.error(addon, f"{where}: invalid id (must match [a-z][a-z0-9_-]*)")
                elif type_id in BASE_ENTITY_TYPES:
                    self.error(addon, f"{where}: id shadows base entity type '{type_id}'")
                elif type_id in seen:
                    self.error(addon, f"{where}: duplicate entity type id (first declared at #{seen[type_id]})")
                else:
                    seen[type_id] = i + 1

            self._field(addon, table, "name", str, where)
            min_level = self._field(addon, table, "min_level", int, where)
            if min_level is not None and not 1 <= min_level <= 3:
                self.error(addon, f"{where}: min_level must be 1, 2 or 3")
            position = self._field(addon, table, "position", str, where)
            if position is not None and position not in POSITIONS:
                self.error(addon, f"{where}: position must be one of {list(POSITIONS)}")
            self._field(addon, table, "icon", str, where, required=False)
            file = self._field(addon, table, "file", str, where)
            if file is None or type_id is None:
                continue
            path = addon.path / file
            if not path.is_file():
                self.error(addon, f"{where}: file '{file}' does not exist")
                continue
            self._check_entity_csv(addon, path, file, type_id, position == "latlon")

    def _check_entity_csv(self, addon: Addon, path: Path, file: str, type_id: str, needs_latlon: bool) -> None:
        rows = self._open_csv(addon, path, file)
        if rows is None:
            return
        if not rows:
            self.error(addon, f"{file}: empty file (expected a header row)")
            return
        header = rows[0]
        if header[:2] != ENTITY_CSV_HEADER_PREFIX:
            self.error(addon, f"{file}: header must start with 'entity,name', got '{','.join(header)}'")
            return
        if needs_latlon and not {"lat", "lon"} <= set(header):
            self.error(addon, f"{file}: position = 'latlon' requires 'lat' and 'lon' columns")
            return
        col = {name: idx for idx, name in enumerate(header)}
        seen: dict[str, int] = {}
        reported = 0
        for lineno, row in enumerate(rows[1:], start=2):
            if not row or all(not c.strip() for c in row):
                continue
            if reported >= MAX_ROW_FINDINGS_PER_FILE:
                self.error(addon, f"{file}: too many problems, further row findings suppressed")
                return
            before = len(self.findings)
            where = f"{file}:{lineno}"
            if len(row) != len(header):
                self.error(addon, f"{where}: expected {len(header)} columns, got {len(row)}")
            else:
                entity = row[col["entity"]].strip()
                if self._check_entity_id(addon, entity, type_id, where):
                    if entity in seen:
                        self.error(addon, f"{where}: duplicate entity '{entity}' (first at line {seen[entity]})")
                    else:
                        seen[entity] = lineno
                if not row[col["name"]].strip():
                    self.error(addon, f"{where}: empty name")
                if needs_latlon:
                    for key, lo, hi in (("lat", -90.0, 90.0), ("lon", -180.0, 180.0)):
                        raw = row[col[key]].strip()
                        if not F64_RE.match(raw) or not lo <= float(raw) <= hi:
                            self.error(addon, f"{where}: {key} '{raw}' is not a valid coordinate")
            if len(self.findings) > before:
                reported += 1

    # -- rules 3, 4, 5, 6 (properties) ---------------------------------------

    def _check_properties(self, addon: Addon) -> None:
        seen: dict[str, int] = {}
        for i, table in enumerate(addon.properties):
            where = f"[[properties]] #{i + 1}"
            self._unknown_keys(addon, table, PROPERTY_KEYS, where)
            prop_id = self._field(addon, table, "id", str, where)
            entity_type = self._field(addon, table, "entity_type", str, where)
            if prop_id is not None and entity_type is not None:
                where = f"[[properties]] '{entity_type}/{prop_id}'"
            if prop_id is not None and not LOCAL_ID_RE.match(prop_id):
                self.error(addon, f"{where}: invalid id '{prop_id}' (must match [a-z][a-z0-9_-]*)")

            local_type: str | None = None
            if entity_type is not None:
                local_type = self._resolve_entity_type(addon, entity_type, where)

            if prop_id is not None and entity_type is not None:
                key = f"{entity_type}/{prop_id}"
                if key in seen:
                    self.error(addon, f"{where}: duplicate property id (first declared at #{seen[key]})")
                else:
                    seen[key] = i + 1

            self._field(addon, table, "name", str, where)
            self._field(addon, table, "unit", str, where)
            dtype = self._field(addon, table, "dtype", str, where)
            if dtype is not None and dtype not in DTYPES:
                self.error(addon, f"{where}: dtype must be one of {list(DTYPES)}")
                dtype = None
            periodicity = self._field(addon, table, "periodicity", str, where)
            if periodicity is not None and periodicity not in PERIODICITIES:
                self.error(addon, f"{where}: periodicity must be one of {list(PERIODICITIES)}")
            self._field(addon, table, "source", str, where)
            self._field(addon, table, "source_url", str, where, required=False)
            self._field(addon, table, "license", str, where, required=False)

            file = self._field(addon, table, "file", str, where)
            if file is None:
                continue
            path = addon.path / file
            if not path.is_file():
                self.error(addon, f"{where}: file '{file}' does not exist")
                continue
            if dtype is None:
                continue  # cannot check values without a valid dtype
            self._check_property_csv(addon, path, file, dtype, local_type)

    def _check_property_csv(
        self, addon: Addon, path: Path, file: str, dtype: str, local_type: str | None
    ) -> None:
        rows = self._open_csv(addon, path, file)
        if rows is None:
            return
        if not rows:
            self.error(addon, f"{file}: empty file (expected header 'entity,period_start,period_end,value')")
            return
        header = rows[0]
        if header != PROPERTY_CSV_HEADER:
            self.error(
                addon,
                f"{file}: header must be exactly 'entity,period_start,period_end,value', "
                f"got '{','.join(header)}'",
            )
            return

        seen: dict[tuple[str, date, date], int] = {}
        data_rows = 0
        reported = 0
        for lineno, row in enumerate(rows[1:], start=2):
            if not row or all(not c.strip() for c in row):
                continue
            if reported >= MAX_ROW_FINDINGS_PER_FILE:
                self.error(addon, f"{file}: too many problems, further row findings suppressed")
                return
            before = len(self.findings)
            where = f"{file}:{lineno}"
            if len(row) != 4:
                self.error(addon, f"{where}: expected 4 columns, got {len(row)}")
                reported += 1
                continue
            entity, start_s, end_s, value = (c.strip() for c in row)

            entity_ok = self._check_entity_id(addon, entity, local_type, where)

            start = parse_period(start_s)
            if start is None:
                self.error(addon, f"{where}: period_start '{start_s}' is not YYYY, YYYY-MM or YYYY-MM-DD")
            if end_s == "":
                end_s = start_s
                end = start
            else:
                end = parse_period(end_s)
                if end is None:
                    self.error(addon, f"{where}: period_end '{end_s}' is not YYYY, YYYY-MM or YYYY-MM-DD")
            if start and end and end[1] < start[0]:
                self.error(addon, f"{where}: period_end '{end_s}' is before period_start '{start_s}'")
                end = None

            if value == "":
                self.warn(addon, f"{where}: empty value, row ignored")
            else:
                problem = check_value(value, dtype)
                if problem:
                    self.error(addon, f"{where}: value {problem} (dtype {dtype})")
                elif entity_ok and start and end:
                    key = (entity, start[0], end[1])
                    if key in seen:
                        self.error(
                            addon,
                            f"{where}: duplicate key ({entity}, {start_s}, {end_s}) "
                            f"(first at line {seen[key]})",
                        )
                    else:
                        seen[key] = lineno
                        data_rows += 1
            if len(self.findings) > before:
                reported += 1

        if data_rows == 0:
            self.warn(addon, f"{file}: no data rows")

    # -- rule 7 --------------------------------------------------------------

    def _check_render(self, addon: Addon) -> None:
        props = {}
        for table in addon.properties:
            et, pid = table.get("entity_type"), table.get("id")
            if isinstance(et, str) and isinstance(pid, str):
                props[f"{et}/{pid}"] = table
        for i, table in enumerate(addon.renders):
            where = f"[[render]] #{i + 1}"
            self._unknown_keys(addon, table, RENDER_KEYS, where)
            prop_ref = self._field(addon, table, "property", str, where)
            kind = self._field(addon, table, "kind", str, where)
            ramp = self._field(addon, table, "ramp", str, where, required=False)
            scale = self._field(addon, table, "scale", str, where, required=False)
            if prop_ref is not None:
                where = f"[[render]] '{prop_ref}'"
                if prop_ref not in props:
                    self.error(
                        addon,
                        f"{where}: property does not exist in this addon "
                        f"(expected '<entity_type>/<id>', one of {sorted(props)})",
                    )
                    prop_ref = None
            if kind is not None and kind not in RENDER_KINDS:
                self.error(addon, f"{where}: kind must be one of {list(RENDER_KINDS)}")
            if scale is not None and scale not in SCALES:
                self.error(addon, f"{where}: scale must be one of {list(SCALES)}")
            if kind == "choropleth":
                if ramp is None:
                    self.warn(addon, f"{where}: choropleth without 'ramp'; the engine default will be used")
                if prop_ref is not None and props[prop_ref].get("dtype") == "str":
                    self.error(addon, f"{where}: choropleth requires a numeric dtype (i64 or f64)")

    def _check_map_overrides(self, addon: Addon) -> None:
        for i, table in enumerate(addon.map_overrides):
            where = f"[[map_overrides]] #{i + 1}"
            self._unknown_keys(addon, table, MAP_OVERRIDE_KEYS, where)
            level = self._field(addon, table, "level", int, where)
            if level is not None and not 1 <= level <= 3:
                self.error(addon, f"{where}: level must be 1, 2 or 3")
            entity = self._field(addon, table, "entity", str, where)
            if entity is not None:
                where = f"[[map_overrides]] '{entity}'"
                m = ENTITY_RE.match(entity)
                if m and m.group(1) not in BASE_ENTITY_TYPES:
                    self._resolve_entity_type(addon, m.group(1), where)
                self._check_entity_id(addon, entity, None, where)
            path = self._field(addon, table, "path", str, where)
            if path is not None:
                target = addon.path / path
                if not target.is_dir():
                    self.error(addon, f"{where}: path '{path}' does not exist or is not a directory")
                elif not any(target.glob("*.bmc")):
                    self.warn(addon, f"{where}: path '{path}' contains no .bmc chunks")
            chunks = self._field(addon, table, "chunks", list, where, required=False)
            if chunks is not None:
                for chunk in chunks:
                    if not (
                        isinstance(chunk, list)
                        and len(chunk) == 2
                        and all(isinstance(c, int) and not isinstance(c, bool) for c in chunk)
                    ):
                        self.error(addon, f"{where}: chunks entries must be [cx, cy] integer pairs, got {chunk!r}")
                        break
            self._field(addon, table, "priority", int, where, required=False)

    # -- hygiene -------------------------------------------------------------

    def _check_unreferenced_files(self, addon: Addon) -> None:
        referenced = set()
        for table in addon.properties + addon.entity_types:
            if isinstance(table.get("file"), str):
                referenced.add((addon.path / table["file"]).resolve())
        data_dir = addon.path / "data"
        if not data_dir.is_dir():
            return
        for csv_path in sorted(data_dir.glob("*.csv")):
            if csv_path.resolve() not in referenced:
                self.warn(addon, f"data/{csv_path.name} is not referenced by any property or entity type")


def _find_cycle(start: str, by_id: dict[str, Addon]) -> list[str] | None:
    """Depth-first search for a dependency path from ``start`` back to itself."""
    stack: list[tuple[str, list[str]]] = [(start, [start])]
    visited: set[str] = set()
    while stack:
        node, path = stack.pop()
        addon = by_id.get(node)
        if addon is None:
            continue
        for dep in addon.depends:
            if dep == start:
                return path
            if dep not in visited:
                visited.add(dep)
                stack.append((dep, path + [dep]))
    return None


def _type_name(types: type | tuple[type, ...]) -> str:
    if isinstance(types, tuple):
        return " or ".join(t.__name__ for t in types)
    return types.__name__


def validate(addons_dirs: AddonsDirs) -> list[Finding]:
    """Validate every addon under ``addons_dirs`` (one path or several) as one set."""
    return Validator(addons_dirs).run()


def has_errors(findings: list[Finding]) -> bool:
    return any(f.level == "ERROR" for f in findings)
