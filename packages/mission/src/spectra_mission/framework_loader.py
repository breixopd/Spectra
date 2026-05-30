"""Dynamic framework loader — loads YAML framework specs into validated Pydantic models.

No hardcoded phase or milestone definitions. All framework data comes from YAML files.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

# ── Pydantic models for framework validation ──────────────────────────


class FrameworkPhase(BaseModel):
    """A single phase within a pentest framework."""

    id: str
    label: str
    description: str = ""
    order: int


class FrameworkMilestone(BaseModel):
    """A milestone mapped to a framework phase."""

    id: str
    label: str
    description: str = ""
    phase: str


class TechniqueConstraint(BaseModel):
    """Constraints on a technique category."""

    max_attempts_per_service: int | None = None
    require_authorization: bool = False


class TechniqueCategory(BaseModel):
    """A technique category that tools can be mapped to."""

    id: str
    label: str
    allowed_in_phases: list[str]
    tool_types: list[str] = []
    requires_consensus: bool = False
    risk_level: str = "medium"
    constraints: TechniqueConstraint | None = None


class ForbiddenTechnique(BaseModel):
    """Technique that is forbidden by default."""

    technique: str
    reason: str
    override: str = "none"


class ReportSection(BaseModel):
    """A section in the generated report."""

    id: str
    label: str
    order: int


class FrameworkMetadata(BaseModel):
    """Framework metadata."""

    name: str
    version: str
    description: str = ""
    url: str = ""


class FrameworkSpec(BaseModel):
    """Complete pentest framework specification loaded from YAML."""

    metadata: FrameworkMetadata
    phases: list[FrameworkPhase]
    milestones: list[FrameworkMilestone]
    technique_categories: list[TechniqueCategory] = []
    forbidden_techniques: list[ForbiddenTechnique] = []
    report_sections: list[ReportSection] = []

    @field_validator("phases")
    @classmethod
    def check_phase_ordering(cls, v: list[FrameworkPhase]) -> list[FrameworkPhase]:
        if not any(p.id == "complete" or p.id == "reporting" for p in v):
            logger.warning("Framework has no terminal phase (complete/reporting)")
        return v

    # ── Convenience accessors ─────────────────────────────────────────

    @property
    def phase_ids(self) -> list[str]:
        return [p.id for p in sorted(self.phases, key=lambda p: p.order)]

    @property
    def phase_labels(self) -> dict[str, str]:
        return {p.id: p.label for p in self.phases}

    @property
    def milestone_ids(self) -> list[str]:
        return [m.id for m in self.milestones]

    @property
    def milestone_labels(self) -> dict[str, str]:
        return {m.id: m.label for m in self.milestones}

    def get_milestones_for_phase(self, phase_id: str) -> list[FrameworkMilestone]:
        return [m for m in self.milestones if m.phase == phase_id]

    def get_allowed_categories(self, phase_id: str) -> list[TechniqueCategory]:
        return [tc for tc in self.technique_categories if phase_id in tc.allowed_in_phases]

    def is_technique_forbidden(self, technique: str) -> ForbiddenTechnique | None:
        for ft in self.forbidden_techniques:
            if ft.technique == technique:
                return ft
        return None


# ── Loader ────────────────────────────────────────────────────────────

_DEFAULT_FRAMEWORK_ID = "ptes"
_FRAMEWORKS_DIR = Path(__file__).parent / "frameworks"


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file, returning empty dict on failure."""
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        logger.exception("Failed to load framework YAML: %s", path)
        return {}


def discover_frameworks() -> dict[str, FrameworkSpec]:
    """Auto-discover all YAML framework specs from the frameworks directory."""
    frameworks: dict[str, FrameworkSpec] = {}
    if not _FRAMEWORKS_DIR.exists():
        logger.warning("Frameworks directory not found: %s", _FRAMEWORKS_DIR)
        return frameworks

    for yaml_file in sorted(_FRAMEWORKS_DIR.glob("*.yaml")):
        framework_id = yaml_file.stem
        raw = _load_yaml(yaml_file)
        if not raw:
            continue
        try:
            spec = FrameworkSpec.model_validate(raw)
            frameworks[framework_id] = spec
            logger.debug("Loaded framework: %s (%s)", framework_id, spec.metadata.name)
        except Exception:
            logger.exception("Invalid framework spec: %s", yaml_file)

    return frameworks


# Global cache — auto-discovered at import time
_ALL_FRAMEWORKS: dict[str, FrameworkSpec] = discover_frameworks()


def get_framework(framework_id: str | None) -> FrameworkSpec:
    """Get a framework spec by ID, defaulting to PTES."""
    fid = framework_id or _DEFAULT_FRAMEWORK_ID
    if fid in _ALL_FRAMEWORKS:
        return _ALL_FRAMEWORKS[fid]
    logger.warning("Framework '%s' not found, falling back to '%s'", fid, _DEFAULT_FRAMEWORK_ID)
    return _ALL_FRAMEWORKS[_DEFAULT_FRAMEWORK_ID]


def list_frameworks() -> list[dict[str, Any]]:
    """List all available frameworks with metadata."""
    return [
        {
            "id": fid,
            "name": spec.metadata.name,
            "version": spec.metadata.version,
            "description": spec.metadata.description,
            "phase_count": len(spec.phases),
            "milestone_count": len(spec.milestones),
        }
        for fid, spec in _ALL_FRAMEWORKS.items()
    ]


def get_default_framework_id() -> str:
    return _DEFAULT_FRAMEWORK_ID


def is_valid_framework(framework_id: str | None) -> bool:
    return (framework_id or _DEFAULT_FRAMEWORK_ID) in _ALL_FRAMEWORKS
