#!/usr/bin/env python
"""CI gate for EXT-4/PD-13: fails the build if any diagnostic_mcp module
outside diagnostic_mcp/providers/ imports a concrete model-provider SDK.

The bridge itself has no model dependency at all (the MCP server never
reasons about anything); provider confinement matters here mainly so it
stays true as the package grows, and so examples/run_diagnostic_session.py
(outside diagnostic_mcp/ entirely) is the only other place a provider
import is expected. Mirrors scripts/check_no_write_imports.py's approach
for BRIDGE-1.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "diagnostic_mcp"
ALLOWED_DIR = PACKAGE_ROOT / "providers"

# Known provider SDK top-level module names. Extend this as new providers
# are added under providers/<name>/.
FORBIDDEN_MODULES = ("anthropic",)


def is_forbidden_import(dotted_name: str) -> bool:
    top_level = dotted_name.split(".")[0]
    return top_level in FORBIDDEN_MODULES


def check_source(source: str, label: str) -> list[str]:
    violations: list[str] = []
    tree = ast.parse(source, filename=label)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if is_forbidden_import(alias.name):
                    violations.append(f"{label}:{node.lineno}: forbidden import '{alias.name}'")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if is_forbidden_import(module):
                violations.append(f"{label}:{node.lineno}: forbidden import from '{module}'")
    return violations


def check_file(path: Path) -> list[str]:
    return check_source(path.read_text(encoding="utf-8"), str(path))


def find_violations() -> list[str]:
    """Every *.py under PACKAGE_ROOT, excluding the one directory allowed
    to import a provider SDK. Shared by main() and the test suite so the
    exclusion rule can't quietly drift between the CI gate and its test."""
    violations: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if ALLOWED_DIR in path.parents:
            continue
        violations.extend(check_file(path))
    return violations


def main() -> int:
    violations = find_violations()

    if violations:
        print("EXT-4/PD-13 violation: provider-SDK import(s) outside providers/:", file=sys.stderr)
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1

    print(f"OK: no provider-SDK imports outside {ALLOWED_DIR} under {PACKAGE_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
