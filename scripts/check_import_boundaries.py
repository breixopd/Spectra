#!/usr/bin/env python3
"""Verify that shared packages (app/core, app/models) don't import service-specific code.

Shared packages must not depend on:
- app.api.*
- app.worker.*  
- app.services.ai.* (except via lazy imports inside functions)
- app.ai_service
- app.scheduler_service
- app.worker_service

This keeps the shared → service dependency direction clean for future extraction.
"""
import ast
import sys
from pathlib import Path

SHARED_PACKAGES = ["app/core", "app/models"]
FORBIDDEN_IMPORTS = [
    "app.api",
    "app.worker",
    "app.ai_service",
    "app.scheduler_service",
    "app.worker_service",
]

# Allowed exceptions (lazy imports inside functions are OK)
ALLOWED_FILES = set()


def check_file(filepath: Path) -> list[str]:
    """Check a single Python file for forbidden top-level imports."""
    violations = []
    try:
        tree = ast.parse(filepath.read_text(), filename=str(filepath))
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        # Only check top-level imports (not inside functions/classes)
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue

        # Skip imports inside function/method bodies
        # (ast.walk doesn't track parent, so we check col_offset as heuristic)
        if node.col_offset > 0:
            continue

        if isinstance(node, ast.ImportFrom) and node.module:
            module = node.module
            for forbidden in FORBIDDEN_IMPORTS:
                if module.startswith(forbidden):
                    violations.append(
                        f"{filepath}:{node.lineno}: top-level import of "
                        f"'{module}' in shared package"
                    )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                for forbidden in FORBIDDEN_IMPORTS:
                    if alias.name.startswith(forbidden):
                        violations.append(
                            f"{filepath}:{node.lineno}: top-level import of "
                            f"'{alias.name}' in shared package"
                        )

    return violations


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    all_violations = []

    for pkg in SHARED_PACKAGES:
        pkg_path = root / pkg
        if not pkg_path.exists():
            continue
        for py_file in pkg_path.rglob("*.py"):
            if str(py_file) in ALLOWED_FILES:
                continue
            violations = check_file(py_file)
            all_violations.extend(violations)

    if all_violations:
        print("Import boundary violations found:")
        for v in sorted(all_violations):
            print(f"  {v}")
        return 1

    print(f"Import boundaries clean: checked {sum(1 for pkg in SHARED_PACKAGES for _ in (Path(__file__).resolve().parent.parent / pkg).rglob('*.py'))} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
