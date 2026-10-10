"""Command-line interface: ``bramapa-data validate|list [ADDONS_DIR]``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .validate import has_errors, load_addons, validate

DEFAULT_ADDONS_DIR = "addons"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bramapa-data",
        description="Validate and inspect Bramapa data addons (spec v0).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="validate every addon under ADDONS_DIR")
    p_validate.add_argument("addons_dir", nargs="?", default=DEFAULT_ADDONS_DIR, metavar="ADDONS_DIR")
    p_validate.add_argument("-q", "--quiet", action="store_true", help="print only ERROR findings")

    p_list = sub.add_parser("list", help="list addons and their canonical property ids")
    p_list.add_argument("addons_dir", nargs="?", default=DEFAULT_ADDONS_DIR, metavar="ADDONS_DIR")
    return parser


def cmd_validate(addons_dir: Path, quiet: bool) -> int:
    findings = validate(addons_dir)
    for finding in findings:
        if quiet and finding.level != "ERROR":
            continue
        print(finding)
    errors = sum(1 for f in findings if f.level == "ERROR")
    warnings = sum(1 for f in findings if f.level == "WARN")
    addon_count = sum(1 for a in load_addons(addons_dir) if a.load_error is None)
    summary = f"{addon_count} addon(s), {errors} error(s), {warnings} warning(s)"
    if has_errors(findings):
        sys.stdout.flush()
        print(f"FAILED: {summary}", file=sys.stderr)
        return 1
    print(f"OK: {summary}")
    return 0


def cmd_list(addons_dir: Path) -> int:
    if not addons_dir.is_dir():
        print(f"ERROR addons: directory not found: {addons_dir}", file=sys.stderr)
        return 1
    status = 0
    for addon in load_addons(addons_dir):
        if addon.load_error or addon.id is None:
            print(f"ERROR {addon.label}: {addon.load_error or 'manifest.toml has no addon.id'}", file=sys.stderr)
            status = 1
            continue
        table = addon.manifest.get("addon", {}) if addon.manifest else {}
        version = table.get("version", "?")
        license_ = table.get("license", "?")
        name = table.get("name", "")
        print(f"{addon.id}  v{version}  [{license_}]  {name}")
        for prop in addon.properties:
            et, pid = prop.get("entity_type"), prop.get("id")
            if not (isinstance(et, str) and isinstance(pid, str)):
                continue
            dtype = prop.get("dtype", "?")
            unit = prop.get("unit", "")
            periodicity = prop.get("periodicity", "?")
            print(f"  {addon.id}/{et}/{pid}  ({dtype}, {unit}, {periodicity})")
        for et in addon.entity_types:
            if isinstance(et.get("id"), str):
                print(f"  entity type {addon.id}/{et['id']}")
    return status


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    addons_dir = Path(args.addons_dir)
    if args.command == "validate":
        return cmd_validate(addons_dir, args.quiet)
    if args.command == "list":
        return cmd_list(addons_dir)
    return 2  # unreachable: argparse enforces the subcommand


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
