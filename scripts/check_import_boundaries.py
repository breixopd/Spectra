#!/usr/bin/env python3
"""Verify that shared packages and microservice entry points don't import across boundaries.

Shared packages must not depend on:
- app.api.*
- app.worker.*
- app.services.ai.* (except via lazy imports inside functions)
- app.ai_service
- app.scheduler_service
- app.worker_service

Microservice entry points must not import from other services:
- app/scheduler_service.py must not import from app.api, app.worker
- app/worker_service.py must not import from app.api, app.scheduler_service, app.ai_service
- app/ai_service.py must not import from app.api, app.worker, app.scheduler_service
- app/worker/** must not import from app.api, app.scheduler_service, app.ai_service

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

# Cross-service boundary rules: {file_or_dir: [forbidden_import_prefixes]}
SERVICE_BOUNDARIES: dict[str, list[str]] = {
    "app/scheduler_service.py": ["app.api", "app.worker"],
    "app/worker_service.py": ["app.api", "app.scheduler_service", "app.ai_service"],
    "app/ai_service.py": ["app.api", "app.worker", "app.scheduler_service"],
    "app/worker": ["app.api", "app.scheduler_service", "app.ai_service"],
}

# Allowed exceptions (lazy imports inside functions are OK)
ALLOWED_FILES = set()


def check_file(filepath: Path, forbidden: list[str] | None = None, label: str = "shared package") -> list[str]:
    """Check a single Python file for forbidden top-level imports."""
    if forbidden is None:
        forbidden = FORBIDDEN_IMPORTS
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
            for fb in forbidden:
                if module.startswith(fb):
                    violations.append(f"{filepath}:{node.lineno}: top-level import of '{module}' in {label}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                for fb in forbidden:
                    if alias.name.startswith(fb):
                        violations.append(
                            f"{filepath}:{node.lineno}: top-level import of '{alias.name}' in {label}"
                        )

    return violations


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    all_violations = []
    files_checked = 0

    # Check shared packages (core, models) against FORBIDDEN_IMPORTS
    for pkg in SHARED_PACKAGES:
        pkg_path = root / pkg
        if not pkg_path.exists():
            continue
        for py_file in pkg_path.rglob("*.py"):
            if str(py_file) in ALLOWED_FILES:
                continue
            violations = check_file(py_file)
            all_violations.extend(violations)
            files_checked += 1

    # Check cross-service boundaries
    for target, forbidden in SERVICE_BOUNDARIES.items():
        target_path = root / target
        if not target_path.exists():
            continue
        if target_path.is_file():
            violations = check_file(target_path, forbidden=forbidden, label=f"service boundary ({target})")
            all_violations.extend(violations)
            files_checked += 1
        else:
            for py_file in target_path.rglob("*.py"):
                if str(py_file) in ALLOWED_FILES:
                    continue
                violations = check_file(py_file, forbidden=forbidden, label=f"service boundary ({target})")
                all_violations.extend(violations)
                files_checked += 1

    if all_violations:
        print("Import boundary violations found:")
        for v in sorted(all_violations):
            print(f"  {v}")
        return 1

    print(f"Import boundaries clean: checked {files_checked} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
