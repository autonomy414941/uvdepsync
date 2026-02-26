from __future__ import annotations

import ast
import importlib.metadata
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import tomlkit

DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
}

REQUIREMENT_NAME_PATTERN = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


@dataclass(frozen=True)
class Analysis:
    project_path: Path
    pyproject_path: Path
    scanned_files: int
    imports: set[str]
    local_modules: set[str]
    inferred_dependencies: set[str]
    declared_dependencies: set[str]
    missing_dependencies: set[str]
    unused_dependencies: set[str]


@dataclass(frozen=True)
class SyncResult:
    changed: bool
    wrote: bool
    before: list[str]
    after: list[str]


def normalize_dist_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirement_name(requirement: str) -> str:
    match = REQUIREMENT_NAME_PATTERN.match(requirement)
    if not match:
        return requirement.strip()
    return match.group(1)


def get_stdlib_modules() -> set[str]:
    if hasattr(sys, "stdlib_module_names"):
        return {module.lower() for module in sys.stdlib_module_names}
    return set()


def discover_local_modules(project_path: Path) -> set[str]:
    local_modules: set[str] = set()

    for child in project_path.iterdir():
        if child.is_file() and child.suffix == ".py":
            local_modules.add(child.stem.lower())
        elif child.is_dir() and (child / "__init__.py").exists():
            local_modules.add(child.name.lower())

    src_dir = project_path / "src"
    if src_dir.is_dir():
        for child in src_dir.iterdir():
            if child.is_file() and child.suffix == ".py":
                local_modules.add(child.stem.lower())
            elif child.is_dir() and (child / "__init__.py").exists():
                local_modules.add(child.name.lower())

    return local_modules


def iter_python_files(project_path: Path, excluded_dirs: set[str]) -> list[Path]:
    python_files: list[Path] = []
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [directory for directory in dirs if directory not in excluded_dirs]
        for file_name in files:
            if file_name.endswith(".py"):
                python_files.append(Path(root) / file_name)
    return python_files


def extract_imports_from_source(source: str) -> set[str]:
    imports: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return imports

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".", 1)[0].lower())
        elif isinstance(node, ast.ImportFrom):
            if node.level != 0 or not node.module:
                continue
            imports.add(node.module.split(".", 1)[0].lower())

    return imports


def collect_imports(project_path: Path, excluded_dirs: set[str]) -> tuple[set[str], int]:
    imports: set[str] = set()
    python_files = iter_python_files(project_path, excluded_dirs)

    for file_path in python_files:
        source = file_path.read_text(encoding="utf-8", errors="ignore")
        imports.update(extract_imports_from_source(source))

    return imports, len(python_files)


def build_distribution_map() -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    raw_map = importlib.metadata.packages_distributions()

    for module_name, distributions in raw_map.items():
        normalized = sorted({normalize_dist_name(dep) for dep in distributions if dep})
        if normalized:
            mapping[module_name.lower()] = normalized

    return mapping


def infer_dependencies(
    imports: set[str],
    distribution_map: Mapping[str, Sequence[str]],
    local_modules: set[str],
    stdlib_modules: set[str],
    explicit_map: Mapping[str, str] | None = None,
) -> set[str]:
    explicit_map = explicit_map or {}
    inferred: set[str] = set()

    for module in imports:
        if module in stdlib_modules or module in local_modules:
            continue

        mapped_dep = explicit_map.get(module)
        if mapped_dep:
            inferred.add(normalize_dist_name(mapped_dep))
            continue

        dep_candidates = distribution_map.get(module)
        if dep_candidates:
            inferred.add(normalize_dist_name(dep_candidates[0]))
        else:
            inferred.add(normalize_dist_name(module))

    return inferred


def load_declared_dependencies(pyproject_path: Path) -> tuple[set[str], list[str]]:
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = data.get("project", {})
    deps = project.get("dependencies", []) or []

    raw_dependencies = [dep for dep in deps if isinstance(dep, str)]
    normalized_dependencies = {
        normalize_dist_name(parse_requirement_name(dep)) for dep in raw_dependencies
    }
    return normalized_dependencies, raw_dependencies


def analyze_project(
    project_path: Path,
    pyproject_path: Path | None = None,
    excluded_dirs: set[str] | None = None,
    explicit_map: Mapping[str, str] | None = None,
    distribution_map: Mapping[str, Sequence[str]] | None = None,
    stdlib_modules: set[str] | None = None,
) -> Analysis:
    project_path = project_path.resolve()
    pyproject_path = pyproject_path or project_path / "pyproject.toml"
    pyproject_path = pyproject_path.resolve()

    if not pyproject_path.exists():
        raise FileNotFoundError(f"pyproject.toml not found at {pyproject_path}")

    excluded_dirs = excluded_dirs or set(DEFAULT_EXCLUDED_DIRS)
    distribution_map = distribution_map or build_distribution_map()
    stdlib_modules = stdlib_modules or get_stdlib_modules()

    imports, scanned_files = collect_imports(project_path, excluded_dirs)
    local_modules = discover_local_modules(project_path)
    inferred_dependencies = infer_dependencies(
        imports=imports,
        distribution_map=distribution_map,
        local_modules=local_modules,
        stdlib_modules=stdlib_modules,
        explicit_map=explicit_map,
    )

    declared_dependencies, _ = load_declared_dependencies(pyproject_path)
    missing_dependencies = inferred_dependencies - declared_dependencies
    unused_dependencies = declared_dependencies - inferred_dependencies

    return Analysis(
        project_path=project_path,
        pyproject_path=pyproject_path,
        scanned_files=scanned_files,
        imports=imports,
        local_modules=local_modules,
        inferred_dependencies=inferred_dependencies,
        declared_dependencies=declared_dependencies,
        missing_dependencies=missing_dependencies,
        unused_dependencies=unused_dependencies,
    )


def compute_synced_dependencies(
    current_dependencies: list[str], inferred_dependencies: set[str]
) -> list[str]:
    current_map: dict[str, str] = {}
    for dep in current_dependencies:
        dep_name = normalize_dist_name(parse_requirement_name(dep))
        current_map.setdefault(dep_name, dep)

    synced: list[str] = []
    for dep_name in sorted(inferred_dependencies):
        synced.append(current_map.get(dep_name, dep_name))

    return synced


def sync_project_dependencies(
    pyproject_path: Path, inferred_dependencies: set[str], write: bool = False
) -> SyncResult:
    source_text = pyproject_path.read_text(encoding="utf-8")
    document = tomlkit.parse(source_text)

    if "project" not in document:
        document["project"] = tomlkit.table()

    project_table = document["project"]
    current_dependencies = [
        dep for dep in project_table.get("dependencies", []) if isinstance(dep, str)
    ]

    synced_dependencies = compute_synced_dependencies(
        current_dependencies=current_dependencies,
        inferred_dependencies=inferred_dependencies,
    )

    changed = current_dependencies != synced_dependencies
    wrote = False

    if changed and write:
        dependency_array = tomlkit.array()
        for dep in synced_dependencies:
            dependency_array.append(dep)
        dependency_array.multiline(True)
        project_table["dependencies"] = dependency_array
        pyproject_path.write_text(tomlkit.dumps(document), encoding="utf-8")
        wrote = True

    return SyncResult(
        changed=changed,
        wrote=wrote,
        before=current_dependencies,
        after=synced_dependencies,
    )
