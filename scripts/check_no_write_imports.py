#!/usr/bin/env python
"""CI gate for BRIDGE-1: fails the build if any diagnostic_mcp module
imports a write-service module.

There is no real Lite service layer in this repo, so this script enforces
a documented naming convention standing in for the real "Lite build fails
if a handler imports a write service" check (see docs/scope.md): any
import whose dotted path contains a segment equal to "write", or ends in
"_write_service", is forbidden. When this package merges into the real
Lite monorepo, point this same check at Lite's actual service-layer
module names instead.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "diagnostic_mcp"

FORBIDDEN_SEGMENT = "write"
FORBIDDEN_SUFFIX = "_write_service"


def is_forbidden_import(dotted_name: str) -> bool:
    segments = dotted_name.split(".")
    return any(seg == FORBIDDEN_SEGMENT for seg in segments) or dotted_name.endswith(
        FORBIDDEN_SUFFIX
    )


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


def main() -> int:
    violations: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        violations.extend(check_file(path))

    if violations:
        print("BRIDGE-1 violation: write-service import(s) found:", file=sys.stderr)
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1

    print(f"OK: no write-service imports found under {PACKAGE_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
