#!/usr/bin/env python3
"""Enforce architecture layer boundaries across languages.

Reads layer definitions from architecture.toml, detects file languages,
extracts imports via thin per-language parsers, and checks for upward
layer violations.

Usage:
    python check_layers.py                          # auto-detect src/<package>/
    python check_layers.py --src src/myproject       # explicit source root
    python check_layers.py --config layers.toml      # alternate config path

Adding a new language:
    1. Write a parser function: (Path, str) -> list[ImportRef]
    2. Register it: PARSERS[".ext"] = your_parser
    See parse_python() for the reference implementation (~20 lines).

Exit codes:
    0 — no violations
    1 — one or more violations found
    2 — configuration error
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[import-not-found,no-redef]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ImportRef:
    """A single intra-package import found in a source file."""

    module: str  # imported module name (e.g. "gateway")
    line: int    # source line number


# ---------------------------------------------------------------------------
# Language parsers
#
# Contract: (path, package) -> list[ImportRef]
#
# Each parser receives a source file and the package name. It returns
# every intra-package module name that file imports, with line numbers.
# External imports are ignored.
# ---------------------------------------------------------------------------

Parser = Callable[[Path, str], list[ImportRef]]


def parse_python(path: Path, package: str) -> list[ImportRef]:
    """Extract intra-package imports from a Python file."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    refs: list[ImportRef] = []

    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)

        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(f"{package}."):
                    refs.append(ImportRef(alias.name.split(".")[1], line))

        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == package:
                for alias in node.names:
                    refs.append(ImportRef(alias.name, line))
            elif node.module.startswith(f"{package}."):
                refs.append(ImportRef(node.module.split(".")[1], line))

    return refs


# ---------------------------------------------------------------------------
# Parser registry
#
# To add a language, write a parser function matching the Parser signature
# and register it here.
# ---------------------------------------------------------------------------

PARSERS: dict[str, Parser] = {
    ".py": parse_python,
}

# Files to skip regardless of extension.
SKIP_FILENAMES: set[str] = {"__init__.py"}


# ---------------------------------------------------------------------------
# Config loading (language-agnostic)
# ---------------------------------------------------------------------------


def load_config(config_path: Path) -> tuple[str, dict[str, int]]:
    """Parse architecture.toml and return (package_name, module_layer_map)."""
    text = config_path.read_text(encoding="utf-8")
    cfg = tomllib.loads(text)

    package = cfg.get("package")
    if not package:
        print("error: 'package' key missing in config", file=sys.stderr)
        sys.exit(2)

    layers = cfg.get("layers", {})
    if not layers:
        print("error: [layers] section is empty", file=sys.stderr)
        sys.exit(2)

    layer_rank: dict[str, int] = {}
    for name, rank in layers.items():
        if not isinstance(rank, int):
            print(
                f"error: layer '{name}' must have an integer rank, "
                f"got {rank!r}",
                file=sys.stderr,
            )
            sys.exit(2)
        layer_rank[name] = rank

    modules = cfg.get("modules", {})
    if not modules:
        print("error: [modules] section is empty", file=sys.stderr)
        sys.exit(2)

    module_layer: dict[str, int] = {}
    for mod, layer_name in modules.items():
        if layer_name not in layer_rank:
            print(
                f"error: module '{mod}' assigned to unknown layer "
                f"'{layer_name}'",
                file=sys.stderr,
            )
            sys.exit(2)
        module_layer[mod] = layer_rank[layer_name]

    return package, module_layer


# ---------------------------------------------------------------------------
# Shared violation logic (language-agnostic)
# ---------------------------------------------------------------------------


def check_violations(
    path: Path,
    import_refs: list[ImportRef],
    current_rank: int,
    module_layer: dict[str, int],
) -> list[str]:
    """Check a list of ImportRefs against the layer DAG. Returns errors."""
    current_module = path.stem
    errors: list[str] = []

    for ref in import_refs:
        imported_rank = module_layer.get(ref.module)
        if imported_rank is None:
            continue

        if imported_rank > current_rank:
            errors.append(
                f"{path}:{ref.line}: "
                f"{current_module} (layer {current_rank}) imports "
                f"{ref.module} (layer {imported_rank}). "
                f"Fix: move the dependency to a lower layer, or "
                f"extract the shared interface into layer "
                f"{current_rank} or below."
            )

    return errors


def validate_file(
    path: Path,
    package: str,
    module_layer: dict[str, int],
) -> list[str]:
    """Parse imports and check layer violations for a single file."""
    if path.name in SKIP_FILENAMES:
        return []

    current_module = path.stem
    current_rank = module_layer.get(current_module)
    if current_rank is None:
        return []

    parser = PARSERS.get(path.suffix)
    if parser is None:
        return []

    import_refs = parser(path, package)
    return check_violations(path, import_refs, current_rank, module_layer)


def validate_source_tree(
    src_root: Path,
    package: str,
    module_layer: dict[str, int],
) -> list[str]:
    """Validate all recognized source files under src_root."""
    errors: list[str] = []
    extensions = set(PARSERS.keys())

    for path in sorted(src_root.iterdir()):
        if path.is_file() and path.suffix in extensions:
            errors.extend(validate_file(path, package, module_layer))

    return errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def find_src_root(package: str) -> Path:
    """Auto-detect src/<package>/ from working directory."""
    candidates = [
        Path("src") / package,
        Path(package),
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate

    print(
        f"error: could not find source root for package '{package}'. "
        f"Tried: {', '.join(str(c) for c in candidates)}. "
        f"Use --src to specify explicitly.",
        file=sys.stderr,
    )
    sys.exit(2)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Check architecture layer boundaries.",
    )
    parser.add_argument(
        "--config",
        default="architecture.toml",
        help="Path to architecture.toml (default: architecture.toml)",
    )
    parser.add_argument(
        "--src",
        default=None,
        help="Source root directory (default: auto-detect from package name)",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"error: config not found: {config_path}", file=sys.stderr)
        sys.exit(2)

    package, module_layer = load_config(config_path)

    src_root = Path(args.src) if args.src else find_src_root(package)
    if not src_root.is_dir():
        print(f"error: source root not found: {src_root}", file=sys.stderr)
        sys.exit(2)

    langs = ", ".join(
        ext.lstrip(".") for ext in sorted(PARSERS.keys())
    )
    errors = validate_source_tree(src_root, package, module_layer)

    if errors:
        print(
            f"Found {len(errors)} layer violation(s):\n",
            file=sys.stderr,
        )
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        sys.exit(1)
    else:
        print(
            f"OK — {len(module_layer)} modules checked "
            f"({langs}), no layer violations."
        )


if __name__ == "__main__":
    main()
