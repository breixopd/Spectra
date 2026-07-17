#!/usr/bin/env python3
"""Boundary checker: enforce package dependency direction across the full workspace.

Rules (from spec section 5.1):
- Bounded packages (packages/*) must NEVER import any service package:
    spectra_api, spectra_ai, spectra_scheduler, spectra_worker
- Services must not import each other:
    services/api  -> must not import spectra_ai, spectra_scheduler, spectra_worker
    services/ai   -> must not import spectra_api, spectra_scheduler, spectra_worker
    services/scheduler -> must not import spectra_api, spectra_ai, spectra_worker
    services/worker    -> must not import spectra_api, spectra_ai, spectra_scheduler

Scan scope: EVERY packages/*/src/**/*.py and services/*/src/**/*.py.
Detects BOTH top-level and lazy/in-function imports.

Baseline mode:
  On first run (or `--generate-baseline`), writes scripts/import_boundary_baseline.json.
  On subsequent runs the checker PASSES if all violations are in the baseline but FAILS
  on any NEW violation not present in the baseline. This lets P2 burn the baseline to zero.

Usage:
    python scripts/check_import_boundaries.py               # baseline mode (default)
    python scripts/check_import_boundaries.py --strict      # fail on ALL violations
    python scripts/check_import_boundaries.py --generate-baseline   # regenerate baseline
    python scripts/check_import_boundaries.py --report      # print full human-readable report
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE_FILE = ROOT / "scripts" / "import_boundary_baseline.json"

# ---------------------------------------------------------------------------
# Service package names (deployable service packages — must never be imported
# by bounded packages or by sibling services).
# ---------------------------------------------------------------------------
SERVICE_PACKAGES = {
    "spectra_api",
    "spectra_ai",
    "spectra_scheduler",
    "spectra_worker",
}

# ---------------------------------------------------------------------------
# Boundary rules:
#   Each entry maps a source-tree path (relative to repo root) to the set of
#   import prefixes that are forbidden within that tree.
# ---------------------------------------------------------------------------
PACKAGE_ROOTS = sorted((ROOT / "packages").glob("*/src"))
SERVICE_ROOTS = sorted((ROOT / "services").glob("*/src"))

# Forbidden imports for bounded packages: any service package import is a violation.
PACKAGE_FORBIDDEN = sorted(SERVICE_PACKAGES)

# Forbidden imports per service: all other services.
SERVICE_FORBIDDEN: dict[str, list[str]] = {
    "services/api/src": [p for p in sorted(SERVICE_PACKAGES) if p != "spectra_api"],
    "services/ai/src": [p for p in sorted(SERVICE_PACKAGES) if p != "spectra_ai"],
    "services/scheduler/src": [p for p in sorted(SERVICE_PACKAGES) if p != "spectra_scheduler"],
    "services/worker/src": [p for p in sorted(SERVICE_PACKAGES) if p != "spectra_worker"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iter_imports(tree: ast.Module) -> list[tuple[ast.stmt, str, bool]]:
    """Yield (node, module_name, is_lazy) for every import in the AST.

    is_lazy=True means the import is inside a function/class body (col_offset > 0
    is a fast but imperfect proxy; we also check parent node depth via a walk).
    """
    results: list[tuple[ast.stmt, str, bool]] = []

    # Build a set of nodes that are direct children of the module (top-level).
    top_level: set[int] = {id(n) for n in ast.iter_child_nodes(tree) if isinstance(n, ast.stmt)}

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        is_lazy = id(node) not in top_level
        if isinstance(node, ast.ImportFrom) and node.module:
            results.append((node, node.module, is_lazy))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                results.append((node, alias.name, is_lazy))
    return results


def check_file(
    filepath: Path,
    forbidden: list[str],
    label: str,
) -> list[dict]:
    """Return a list of violation dicts for a single file."""
    violations: list[dict] = []
    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    for node, module, is_lazy in _iter_imports(tree):
        for fb in forbidden:
            if module == fb or module.startswith(fb + "."):
                violations.append(
                    {
                        "file": str(filepath.relative_to(ROOT)),
                        "line": node.lineno,
                        "module": module,
                        "label": label,
                        "lazy": is_lazy,
                        "key": f"{filepath.relative_to(ROOT)}:{node.lineno}:{module}",
                    }
                )
    return violations


def scan_tree(
    tree_path: Path,
    forbidden: list[str],
    label: str,
) -> list[dict]:
    """Scan every .py file under tree_path and return all violations."""
    if not tree_path.exists():
        return []
    violations: list[dict] = []
    for py_file in sorted(tree_path.rglob("*.py")):
        violations.extend(check_file(py_file, forbidden, label))
    return violations


# ---------------------------------------------------------------------------
# Baseline I/O
# ---------------------------------------------------------------------------


def load_baseline() -> set[str]:
    if not BASELINE_FILE.exists():
        return set()
    try:
        data = json.loads(BASELINE_FILE.read_text())
        return set(data.get("violation_keys", []))
    except (json.JSONDecodeError, KeyError):
        return set()


def write_baseline(violations: list[dict]) -> None:
    keys = sorted({v["key"] for v in violations})
    payload = {
        "description": (
            "Baseline of known import-boundary violations as of P0. "
            "Burn this list to zero in P2. "
            "The checker passes when all violations are in this set "
            "and fails on any NEW violation not listed here."
        ),
        "count": len(keys),
        "violation_keys": keys,
    }
    BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_FILE.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Baseline written to {BASELINE_FILE.relative_to(ROOT)} ({len(keys)} violations)")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_report(violations: list[dict], *, new_only: bool = False, baseline: set[str]) -> None:
    label = "NEW violations (not in baseline)" if new_only else "All violations"
    items = [v for v in violations if v["key"] not in baseline] if new_only else violations
    if not items:
        print(f"{label}: none")
        return
    print(f"\n{label} ({len(items)}):")
    for v in sorted(items, key=lambda x: (x["file"], x["line"])):
        lazy_tag = " [lazy/in-function]" if v["lazy"] else " [top-level]"
        print(f"  {v['file']}:{v['line']}: imports '{v['module']}' in {v['label']}{lazy_tag}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    strict = "--strict" in args
    generate_baseline = "--generate-baseline" in args
    report = "--report" in args

    all_violations: list[dict] = []
    files_checked = 0

    # Scan all bounded packages (packages/*/src)
    for pkg_src in PACKAGE_ROOTS:
        pkg_name = pkg_src.parent.name  # e.g. "platform"
        label = f"packages/{pkg_name} (bounded package)"
        violations = scan_tree(pkg_src, PACKAGE_FORBIDDEN, label)
        all_violations.extend(violations)
        files_checked += sum(1 for _ in pkg_src.rglob("*.py")) if pkg_src.exists() else 0

    # Scan all services (services/*/src)
    for svc_src in SERVICE_ROOTS:
        svc_key = str(svc_src.relative_to(ROOT))
        forbidden = SERVICE_FORBIDDEN.get(svc_key, [])
        if not forbidden:
            continue
        svc_name = svc_src.parent.name  # e.g. "api"
        label = f"services/{svc_name} (service boundary)"
        violations = scan_tree(svc_src, forbidden, label)
        all_violations.extend(violations)
        files_checked += sum(1 for _ in svc_src.rglob("*.py")) if svc_src.exists() else 0

    # Deduplicate (same import can appear as both top-level and lazy due to AST walk)
    seen_keys: set[str] = set()
    deduped: list[dict] = []
    for v in all_violations:
        if v["key"] not in seen_keys:
            seen_keys.add(v["key"])
            deduped.append(v)
    all_violations = deduped

    # Handle --generate-baseline: write and exit 0
    if generate_baseline:
        write_baseline(all_violations)
        if report:
            print_report(all_violations, new_only=False, baseline=set())
        return 0

    baseline = load_baseline()
    new_violations = [v for v in all_violations if v["key"] not in baseline]
    baseline_violations = [v for v in all_violations if v["key"] in baseline]

    # Summary line
    print(
        f"Import boundary check: {files_checked} files scanned, "
        f"{len(all_violations)} total violations "
        f"({len(baseline_violations)} baselined, {len(new_violations)} NEW)"
    )

    # Always print new violations
    if new_violations or report:
        print_report(all_violations, new_only=not report, baseline=baseline)

    if report and baseline_violations:
        print(f"\nBaselined violations ({len(baseline_violations)}) — tracked for P2 burn-down:")
        for v in sorted(baseline_violations, key=lambda x: (x["file"], x["line"])):
            lazy_tag = " [lazy]" if v["lazy"] else ""
            print(f"  {v['file']}:{v['line']}: '{v['module']}'{lazy_tag}")

    if strict:
        if all_violations:
            print(
                f"\nFAIL (--strict): {len(all_violations)} violations (including baselined). "
                "Use P2 to eliminate all violations."
            )
            return 1
        print(f"\nPASS (--strict): 0 violations across {files_checked} files")
        return 0

    # Baseline mode (default): pass if no NEW violations
    if new_violations:
        print(
            f"\nFAIL: {len(new_violations)} NEW violation(s) not in baseline. "
            "Fix them or regenerate the baseline after deliberate review."
        )
        return 1

    if all_violations:
        print(
            f"PASS (baseline mode): {len(baseline_violations)} known violation(s) within baseline. "
            "Run with --report for details. Burn them down in P2."
        )
    else:
        print(f"PASS: 0 violations across {files_checked} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
