from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from uvdepsync.core import (
    Analysis,
    DEFAULT_EXCLUDED_DIRS,
    analyze_project,
    sync_project_dependencies,
)


def parse_map_values(entries: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for entry in entries:
        if "=" not in entry:
            raise ValueError(f"Invalid --map value '{entry}'. Use module=distribution.")
        module, dependency = entry.split("=", 1)
        module = module.strip().lower()
        dependency = dependency.strip()
        if not module or not dependency:
            raise ValueError(f"Invalid --map value '{entry}'. Use module=distribution.")
        mapping[module] = dependency
    return mapping


def analysis_to_dict(analysis: Analysis) -> dict[str, object]:
    return {
        "project_path": str(analysis.project_path),
        "pyproject_path": str(analysis.pyproject_path),
        "scanned_files": analysis.scanned_files,
        "imports": sorted(analysis.imports),
        "local_modules": sorted(analysis.local_modules),
        "inferred_dependencies": sorted(analysis.inferred_dependencies),
        "declared_dependencies": sorted(analysis.declared_dependencies),
        "missing_dependencies": sorted(analysis.missing_dependencies),
        "unused_dependencies": sorted(analysis.unused_dependencies),
    }


def print_analysis(analysis: Analysis) -> None:
    data = analysis_to_dict(analysis)

    print(f"Scanned files: {data['scanned_files']}")
    print(f"Inferred dependencies: {', '.join(data['inferred_dependencies']) or '(none)'}")
    print(f"Declared dependencies: {', '.join(data['declared_dependencies']) or '(none)'}")
    print(f"Missing dependencies: {', '.join(data['missing_dependencies']) or '(none)'}")
    print(f"Unused dependencies: {', '.join(data['unused_dependencies']) or '(none)'}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uvdepsync",
        description="Sync pyproject dependencies from Python imports.",
    )
    parser.add_argument(
        "--project-path",
        default=".",
        help="Project directory to scan (default: current directory).",
    )
    parser.add_argument(
        "--pyproject",
        default=None,
        help="Explicit path to pyproject.toml (default: <project-path>/pyproject.toml).",
    )
    parser.add_argument(
        "--exclude-dir",
        action="append",
        default=[],
        help="Directory name to exclude from scanning. Can be provided multiple times.",
    )
    parser.add_argument(
        "--map",
        action="append",
        default=[],
        help="Manual import mapping in module=distribution format. Can be provided multiple times.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect", help="Print inferred/declarative dependency diff."
    )
    inspect_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )

    subparsers.add_parser(
        "check",
        help="Exit with code 1 if missing or unused dependencies are found.",
    )

    sync_parser = subparsers.add_parser(
        "sync",
        help="Preview or apply dependency sync to pyproject.toml.",
    )
    sync_parser.add_argument(
        "--write",
        action="store_true",
        help="Write updated dependencies to pyproject.toml.",
    )
    sync_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    project_path = Path(args.project_path).resolve()
    pyproject_path = Path(args.pyproject).resolve() if args.pyproject else None
    excluded_dirs = set(DEFAULT_EXCLUDED_DIRS).union(args.exclude_dir)

    try:
        explicit_map = parse_map_values(args.map)
    except ValueError as error:
        parser.error(str(error))

    analysis = analyze_project(
        project_path=project_path,
        pyproject_path=pyproject_path,
        excluded_dirs=excluded_dirs,
        explicit_map=explicit_map,
    )

    if args.command == "inspect":
        if args.json:
            print(json.dumps(analysis_to_dict(analysis), indent=2, sort_keys=True))
        else:
            print_analysis(analysis)
        return 0

    if args.command == "check":
        print_analysis(analysis)
        if analysis.missing_dependencies or analysis.unused_dependencies:
            return 1
        return 0

    if args.command == "sync":
        result = sync_project_dependencies(
            pyproject_path=analysis.pyproject_path,
            inferred_dependencies=analysis.inferred_dependencies,
            write=args.write,
        )

        payload = {
            "changed": result.changed,
            "wrote": result.wrote,
            "before": result.before,
            "after": result.after,
            "missing_dependencies": sorted(analysis.missing_dependencies),
            "unused_dependencies": sorted(analysis.unused_dependencies),
        }

        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print_analysis(analysis)
            if not result.changed:
                print("No dependency changes needed.")
            elif args.write:
                print(f"Updated {analysis.pyproject_path} with synced dependencies.")
            else:
                print("Dry run only. Re-run with --write to apply changes.")
                print(f"Current: {', '.join(result.before) or '(none)'}")
                print(f"Synced: {', '.join(result.after) or '(none)'}")

        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
