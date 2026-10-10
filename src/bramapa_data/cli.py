"""Command-line interface: ``bramapa-data validate|list|build|inspect``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .bmd import HEADER_SIZE, date_from_days, decode
from .build import BuildError, build
from .validate import has_errors, load_addons, validate

DEFAULT_ADDONS_DIR = "addons"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bramapa-data",
        description="Validate, build and inspect Bramapa data addons (spec v0).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    dirs_help = (
        f"one or more addon root directories, validated as a single set (default: {DEFAULT_ADDONS_DIR})"
    )
    p_validate = sub.add_parser("validate", help="validate every addon under the ADDONS_DIR roots")
    p_validate.add_argument("addons_dirs", nargs="*", default=[DEFAULT_ADDONS_DIR], metavar="ADDONS_DIR", help=dirs_help)
    p_validate.add_argument("-q", "--quiet", action="store_true", help="print only ERROR findings")

    p_list = sub.add_parser("list", help="list addons and their canonical property ids")
    p_list.add_argument("addons_dirs", nargs="*", default=[DEFAULT_ADDONS_DIR], metavar="ADDONS_DIR", help=dirs_help)

    p_build = sub.add_parser("build", help="validate, then write .bmd files and index.toml to --out")
    p_build.add_argument("addons_dirs", nargs="*", default=[DEFAULT_ADDONS_DIR], metavar="ADDONS_DIR", help=dirs_help)
    p_build.add_argument("--out", required=True, metavar="DIR", help="output directory (created if missing)")
    p_build.add_argument("-q", "--quiet", action="store_true", help="print only ERROR findings and the summary")

    p_inspect = sub.add_parser("inspect", help="print the header and first rows of a .bmd file")
    p_inspect.add_argument("file", metavar="FILE.bmd")
    p_inspect.add_argument("-n", "--rows", type=int, default=10, help="rows to print (default 10, 0 = all)")
    return parser


def cmd_validate(addons_dirs: list[Path], quiet: bool) -> int:
    findings = validate(addons_dirs)
    for finding in findings:
        if quiet and finding.level != "ERROR":
            continue
        print(finding)
    errors = sum(1 for f in findings if f.level == "ERROR")
    warnings = sum(1 for f in findings if f.level == "WARN")
    addon_count = sum(1 for a in load_addons(addons_dirs) if a.load_error is None)
    summary = f"{addon_count} addon(s), {errors} error(s), {warnings} warning(s)"
    if has_errors(findings):
        sys.stdout.flush()
        print(f"FAILED: {summary}", file=sys.stderr)
        return 1
    print(f"OK: {summary}")
    return 0


def cmd_list(addons_dirs: list[Path]) -> int:
    missing = [d for d in addons_dirs if not d.is_dir()]
    for addons_dir in missing:
        print(f"ERROR addons: directory not found: {addons_dir}", file=sys.stderr)
    if missing:
        return 1
    status = 0
    for addon in load_addons(addons_dirs):
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


def cmd_build(addons_dirs: list[Path], out_dir: Path, quiet: bool) -> int:
    try:
        result = build(addons_dirs, out_dir)
    except BuildError as exc:
        for finding in exc.findings:
            if quiet and finding.level != "ERROR":
                continue
            print(finding)
        sys.stdout.flush()
        print(f"FAILED: {exc}; nothing written", file=sys.stderr)
        return 1
    if not quiet:
        for finding in result.findings:
            print(finding)
    for prop in result.properties:
        if prop.period_min is None or prop.period_max is None:
            span = "no rows"
        else:
            span = f"{date_from_days(prop.period_min).isoformat()}..{date_from_days(prop.period_max).isoformat()}"
        print(f"{prop.id}: {prop.rows} rows, {span} -> {prop.file}")
    print(f"OK: {len(result.addons)} addon(s), {len(result.properties)} propert(y/ies) written to {out_dir}")
    return 0


def cmd_inspect(file: Path, limit: int) -> int:
    try:
        data = file.read_bytes()
    except OSError as exc:
        print(f"ERROR {file}: {exc}", file=sys.stderr)
        return 1
    try:
        decoded = decode(data)
    except (ValueError, Exception) as exc:  # zstd errors are not ValueErrors
        print(f"ERROR {file}: not a valid .bmd file: {exc}", file=sys.stderr)
        return 1
    h = decoded.header
    print(f"file:          {file} ({len(data)} bytes)")
    print(f"magic:         BMDT  spec_version={h.spec_version}")
    print(f"dtype:         {h.dtype}")
    print(f"row_count:     {h.row_count}")
    print(f"entity_count:  {h.entity_count}")
    print(f"string_count:  {h.string_count}")
    print(f"payload_len:   {h.payload_len} (zstd; header {HEADER_SIZE} bytes)")
    shown = ", ".join(decoded.entities[:8]) + (", ..." if len(decoded.entities) > 8 else "")
    print(f"entities:      {shown}")
    if decoded.strings:
        shown = ", ".join(repr(s) for s in decoded.strings[:8]) + (", ..." if len(decoded.strings) > 8 else "")
        print(f"strings:       {shown}")
    rows = decoded.rows if limit <= 0 else decoded.rows[:limit]
    print(f"rows ({len(rows)} of {h.row_count}):")
    print("  entity_idx  entity               period_start  period_end    value")
    idx = {e: i for i, e in enumerate(decoded.entities)}
    for r in rows:
        start = date_from_days(r.period_start).isoformat()
        end = date_from_days(r.period_end).isoformat()
        value = repr(r.value) if h.dtype == "str" else str(r.value)
        print(f"  {idx[r.entity]:<10}  {r.entity:<20} {start}    {end}    {value}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate":
        return cmd_validate([Path(d) for d in args.addons_dirs], args.quiet)
    if args.command == "list":
        return cmd_list([Path(d) for d in args.addons_dirs])
    if args.command == "build":
        return cmd_build([Path(d) for d in args.addons_dirs], Path(args.out), args.quiet)
    if args.command == "inspect":
        return cmd_inspect(Path(args.file), args.rows)
    return 2  # unreachable: argparse enforces the subcommand


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
