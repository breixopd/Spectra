"""CVSS 3.1 score calculator."""

import math
import re

# Metric value weights per CVSS 3.1 specification
_WEIGHTS: dict[str, dict[str, float]] = {
    "AV": {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.20},
    "AC": {"L": 0.77, "H": 0.44},
    "PR": {
        # Unchanged scope
        "N_U": 0.85, "L_U": 0.62, "H_U": 0.27,
        # Changed scope
        "N_C": 0.85, "L_C": 0.68, "H_C": 0.50,
    },
    "UI": {"N": 0.85, "R": 0.62},
    "S": {"U": False, "C": True},  # scope changed flag
    "C": {"N": 0.0, "L": 0.22, "H": 0.56},
    "I": {"N": 0.0, "L": 0.22, "H": 0.56},
    "A": {"N": 0.0, "L": 0.22, "H": 0.56},
}

_METRIC_ORDER = ["AV", "AC", "PR", "UI", "S", "C", "I", "A"]

_VECTOR_RE = re.compile(
    r"^CVSS:3\.[01]/"
    r"AV:[NALP]/AC:[LH]/PR:[NLH]/UI:[NR]/S:[UC]/"
    r"C:[NLH]/I:[NLH]/A:[NLH]$"
)


def _roundup(x: float) -> float:
    """CVSS 3.1 roundup function: smallest (0.1 step) >= x."""
    return math.ceil(x * 10) / 10


def _severity(score: float) -> str:
    if score == 0.0:
        return "None"
    if score <= 3.9:
        return "Low"
    if score <= 6.9:
        return "Medium"
    if score <= 8.9:
        return "High"
    return "Critical"


def calculate_cvss31(vector: str) -> dict:
    """Calculate CVSS 3.1 base score from a vector string.

    Returns dict with base_score, severity, impact_subscore, exploitability_subscore.
    Raises ValueError on invalid vector.
    """
    vector = vector.strip()
    if not _VECTOR_RE.match(vector):
        raise ValueError(f"Invalid CVSS 3.1 vector: {vector}")

    # Parse metrics
    parts = vector.split("/")
    metrics: dict[str, str] = {}
    for part in parts[1:]:  # skip "CVSS:3.1"
        key, val = part.split(":")
        metrics[key] = val

    scope_changed = metrics["S"] == "C"

    # Privilege Required weight depends on scope
    pr_suffix = "_C" if scope_changed else "_U"
    pr_weight = _WEIGHTS["PR"][metrics["PR"] + pr_suffix]

    # Exploitability sub-score
    exploitability = (
        8.22
        * _WEIGHTS["AV"][metrics["AV"]]
        * _WEIGHTS["AC"][metrics["AC"]]
        * pr_weight
        * _WEIGHTS["UI"][metrics["UI"]]
    )

    # Impact sub-score
    isc_base = 1 - (
        (1 - _WEIGHTS["C"][metrics["C"]])
        * (1 - _WEIGHTS["I"][metrics["I"]])
        * (1 - _WEIGHTS["A"][metrics["A"]])
    )

    if scope_changed:
        impact = 7.52 * (isc_base - 0.029) - 3.25 * (isc_base - 0.02) ** 15
    else:
        impact = 6.42 * isc_base

    # Base score
    if impact <= 0:
        base_score = 0.0
    elif scope_changed:
        base_score = _roundup(min(1.08 * (impact + exploitability), 10))
    else:
        base_score = _roundup(min(impact + exploitability, 10))

    return {
        "base_score": base_score,
        "severity": _severity(base_score),
        "impact_subscore": round(impact, 1),
        "exploitability_subscore": round(exploitability, 1),
        "vector": vector,
    }
