#!/usr/bin/env python3
"""Verify that shared packages and microservice entry points don't import across boundaries.

Shared packages must not depend on:
- app.api.*
- spectra_worker.* (worker implementation package)
- app.services.ai.* (except via lazy imports inside functions)
- app.services.ai.__main__
- app.services.scheduler.__main__
- spectra_worker.__main__

Microservice entry points must not import from other services:
- app/services/scheduler/__main__.py must not import from app.api, spectra_worker
- services/worker/src/spectra_worker/__main__.py must not import from app.api, app.services.scheduler.__main__, app.services.ai.__main__
- app/services/ai/__main__.py must not import from app.api, spectra_worker, app.services.scheduler.__main__
- services/worker/src/** must not import from app.api, app.services.scheduler.__main__, app.services.ai.__main__

This keeps the shared → service dependency direction clean for future extraction.
"""

import ast
import sys
from pathlib import Path

SHARED_PACKAGES = ["app/core", "app/models", "packages/common/src", "packages/domain/src", "packages/tools-core/src"]
FORBIDDEN_IMPORTS = [
    "app.api",
    "spectra_worker",
    "app.services.ai",
    "app.services.scheduler.__main__",
    "spectra_worker.__main__",
]

# Cross-service boundary rules: {file_or_dir: [forbidden_import_prefixes]}
SERVICE_BOUNDARIES: dict[str, list[str]] = {
    "app/services/scheduler/__main__.py": ["app.api", "spectra_worker"],
    "services/worker/src/spectra_worker/__main__.py": ["app.api", "app.services.scheduler.__main__", "app.services.ai.__main__"],
    "app/services/ai/__main__.py": ["app.api", "spectra_worker", "app.services.scheduler.__main__"],
    # API layer must not import AI inference modules at top level.
    # Pure-data submodules (cost_tracker, cve_intel, etc.) use lazy imports only.
    "app/api": ["app.services.ai"],
    "services/api/src": ["spectra_ai", "spectra_scheduler", "spectra_worker"],
    "services/ai/src": ["app.api", "spectra_api", "spectra_scheduler", "spectra_worker"],
    "services/scheduler/src": ["app.api", "spectra_api", "spectra_ai", "spectra_worker"],
    "services/worker/src": ["app.api", "app.services.scheduler.__main__", "app.services.ai.__main__", "spectra_api", "spectra_ai", "spectra_scheduler"],
}

# Known cross-service couplings (lazy imports) — emitted as warnings, not failures.
# worker → app.services.ai: tool jobs use AI service for RAG/LLM features at runtime.
# api → app.services.ai: pure-data submodules (cost_tracker, cve_intel, memory, etc.)
#   accessed via lazy imports for read-only data that doesn't need LLM inference.
WARN_LAZY_IMPORTS: dict[str, list[str]] = {
    "services/worker/src": ["app.services.ai"],
    "app/api": ["app.services.ai"],
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


def check_lazy_imports(filepath: Path, warned: list[str]) -> list[str]:
    """Detect lazy (non-top-level) imports matching warned prefixes. Returns warnings, not errors."""
    warnings = []
    try:
        tree = ast.parse(filepath.read_text(), filename=str(filepath))
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        # Only interested in indented (lazy) imports
        if node.col_offset == 0:
            continue
        if isinstance(node, ast.ImportFrom) and node.module:
            for prefix in warned:
                if node.module.startswith(prefix):
                    warnings.append(
                        f"{filepath}:{node.lineno}: lazy import of '{node.module}' (known coupling)"
                    )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                for prefix in warned:
                    if alias.name.startswith(prefix):
                        warnings.append(
                            f"{filepath}:{node.lineno}: lazy import of '{alias.name}' (known coupling)"
                        )
    return warnings


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

    # Warn about known lazy cross-service imports (non-blocking)
    all_warnings: list[str] = []
    for target, warned_prefixes in WARN_LAZY_IMPORTS.items():
        target_path = root / target
        if not target_path.exists():
            continue
        py_files = [target_path] if target_path.is_file() else target_path.rglob("*.py")
        for py_file in py_files:
            all_warnings.extend(check_lazy_imports(py_file, warned_prefixes))

    if all_warnings:
        print(f"Cross-service coupling warnings ({len(all_warnings)}):")
        for w in sorted(all_warnings):
            print(f"  WARNING: {w}")

    if all_violations:
        print("Import boundary violations found:")
        for v in sorted(all_violations):
            print(f"  {v}")
        return 1

    print(f"Import boundaries clean: checked {files_checked} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
