# uvdepsync

`uvdepsync` keeps `[project.dependencies]` in `pyproject.toml` aligned with actual Python imports.

It is designed for `uv`/PEP 621 projects that want:
- quick import-based dependency detection,
- CI checks for missing/unused dependencies,
- deterministic sync with optional write mode.

## Why

`uv` users have requested pipreqs-like dependency detection from imports, but this is not currently a short-term core `uv` feature. `uvdepsync` provides this as a focused third-party CLI.

## Install

```bash
pip install git+https://github.com/autonomy414941/uvdepsync.git
```

Or from source:

```bash
pip install .
```

## Usage

Inspect inferred vs declared dependencies:

```bash
uvdepsync inspect
```

CI check (exit code `1` if drift exists):

```bash
uvdepsync check
```

Preview sync changes:

```bash
uvdepsync sync
```

Write synced dependencies to `pyproject.toml`:

```bash
uvdepsync sync --write
```

Add explicit import mapping for ambiguous module names:

```bash
uvdepsync --map sklearn=scikit-learn inspect
```

## What It Does

1. Scans Python files and extracts top-level imports via AST.
2. Excludes stdlib modules and obvious local project modules.
3. Maps imports to distribution names using installed metadata.
4. Diffs inferred dependencies against `[project.dependencies]`.
5. Optionally rewrites `[project.dependencies]` in sorted, deterministic order.

## Limitations

- Mapping from import name to distribution name can be ambiguous without explicit `--map` overrides.
- It currently syncs only `[project.dependencies]` (not optional dependency groups).

## License

MIT
