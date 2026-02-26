from __future__ import annotations

import tomllib
from pathlib import Path

from uvdepsync.core import (
    analyze_project,
    extract_imports_from_source,
    sync_project_dependencies,
)


def write_pyproject(path: Path, dependencies: list[str]) -> None:
    deps_text = "\n".join([f'    "{dep}",' for dep in dependencies])
    path.write_text(
        "\n".join(
            [
                "[project]",
                'name = "sample"',
                'version = "0.1.0"',
                "dependencies = [",
                deps_text,
                "]",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_extract_imports_from_source_handles_import_and_from() -> None:
    source = """
import os
import requests.sessions
from click import echo
from pkg.sub import run
from .local import helper
"""

    imports = extract_imports_from_source(source)

    assert imports == {"os", "requests", "click", "pkg"}


def test_analyze_project_detects_missing_and_unused_dependencies(tmp_path: Path) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    write_pyproject(pyproject_path, ["requests>=2.0", "unusedpkg"])

    (tmp_path / "app.py").write_text(
        "\n".join(
            [
                "import os",
                "import requests",
                "import click",
                "import localmod",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "localmod.py").write_text("value = 1\n", encoding="utf-8")

    analysis = analyze_project(
        project_path=tmp_path,
        pyproject_path=pyproject_path,
        distribution_map={
            "requests": ["requests"],
            "click": ["click"],
            "localmod": ["localmod"],
        },
        stdlib_modules={"os"},
    )

    assert analysis.scanned_files == 2
    assert analysis.inferred_dependencies == {"requests", "click"}
    assert analysis.declared_dependencies == {"requests", "unusedpkg"}
    assert analysis.missing_dependencies == {"click"}
    assert analysis.unused_dependencies == {"unusedpkg"}


def test_sync_project_dependencies_dry_run_and_write(tmp_path: Path) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    write_pyproject(pyproject_path, ["requests>=2.0", "unusedpkg"])

    dry_run = sync_project_dependencies(
        pyproject_path=pyproject_path,
        inferred_dependencies={"requests", "click"},
        write=False,
    )
    assert dry_run.changed is True
    assert dry_run.wrote is False
    assert dry_run.before == ["requests>=2.0", "unusedpkg"]
    assert dry_run.after == ["click", "requests>=2.0"]

    write_result = sync_project_dependencies(
        pyproject_path=pyproject_path,
        inferred_dependencies={"requests", "click"},
        write=True,
    )
    assert write_result.changed is True
    assert write_result.wrote is True

    parsed = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    assert parsed["project"]["dependencies"] == ["click", "requests>=2.0"]
