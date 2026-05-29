"""Framework enforcer — validates actions against the active framework's constraints.

Checks:
- Is the technique category allowed in the current phase?
- Is the technique forbidden by the framework?
- Does the action require consensus?
- Are there technique-specific constraints (e.g., max attempts)?

All validation is data-driven from the framework YAML spec. No hardcoded rules.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from spectra_platform.services.mission.framework_loader import (
    FrameworkSpec,
    ForbiddenTechnique,
    TechniqueCategory,
    get_framework,
)

logger = logging.getLogger(__name__)


@dataclass
class EnforcementResult:
    """Result of a framework enforcement check."""

    allowed: bool
    reason: str = ""
    requires_consensus: bool = False
    risk_level: str = "medium"
    constraints: dict = field(default_factory=dict)
    blocked_by: ForbiddenTechnique | None = None


class FrameworkEnforcer:
    """Validates proposed pentest actions against the active framework + policy."""

    def __init__(self, framework_id: str | None = None):
        self.spec: FrameworkSpec = get_framework(framework_id)

    # ── Phase validation ──────────────────────────────────────────────

    def is_valid_phase(self, phase_id: str) -> bool:
        """Check if a phase ID exists in the framework."""
        return any(p.id == phase_id for p in self.spec.phases)

    def get_next_phase(self, current_phase_id: str) -> str | None:
        """Get the next phase after current, or None if at terminal phase."""
        ordered = sorted(self.spec.phases, key=lambda p: p.order)
        for i, p in enumerate(ordered):
            if p.id == current_phase_id and i + 1 < len(ordered):
                return ordered[i + 1].id
        return None

    # ── Technique validation ──────────────────────────────────────────

    def check_technique(
        self,
        technique_category: str,
        phase_id: str,
        *,
        attempt_count: int = 0,
    ) -> EnforcementResult:
        """Validate whether a technique category is allowed in the given phase.

        Args:
            technique_category: The technique category ID from the framework spec
            phase_id: Current assessment phase
            attempt_count: Number of attempts made so far (for rate-limited techniques)

        Returns:
            EnforcementResult with allowed status, reason, and any constraints
        """
        # Check if technique is forbidden
        forbidden = self.spec.is_technique_forbidden(technique_category)
        if forbidden:
            if forbidden.override == "none":
                return EnforcementResult(
                    allowed=False,
                    reason=f"Forbidden: {forbidden.reason}",
                    blocked_by=forbidden,
                )
            # Has override (e.g., explicit_authorization) — allow but flag it
            logger.info(
                "Technique '%s' is forbidden but override '%s' may allow it: %s",
                technique_category,
                forbidden.override,
                forbidden.reason,
            )

        # Find the category definition
        cat = self._find_category(technique_category)
        if cat is None:
            # Not a known technique category — if it was forbidden with override, allow it
            if forbidden:
                return EnforcementResult(
                    allowed=True,
                    reason=f"Forbidden but overrideable ('{forbidden.override}'): {forbidden.reason}",
                    blocked_by=forbidden,
                )
            logger.warning(
                "Technique category '%s' not defined in framework '%s'",
                technique_category,
                self.spec.metadata.name,
            )
            return EnforcementResult(
                allowed=False,
                reason=f"Unknown technique category: {technique_category}",
            )

        # Check phase allowlist
        if phase_id not in cat.allowed_in_phases:
            return EnforcementResult(
                allowed=False,
                reason=f"Technique '{cat.label}' not allowed in phase '{phase_id}'. "
                f"Allowed phases: {cat.allowed_in_phases}",
            )

        # Check attempt constraints
        constraints = {}
        if cat.constraints and cat.constraints.max_attempts_per_service:
            if attempt_count >= cat.constraints.max_attempts_per_service:
                return EnforcementResult(
                    allowed=False,
                    reason=f"Max attempts ({cat.constraints.max_attempts_per_service}) "
                    f"exceeded for '{cat.label}'",
                )

        return EnforcementResult(
            allowed=True,
            requires_consensus=cat.requires_consensus,
            risk_level=cat.risk_level,
            constraints=constraints,
        )

    def get_allowed_techniques(self, phase_id: str) -> list[TechniqueCategory]:
        """Get all technique categories allowed in a given phase."""
        return self.spec.get_allowed_categories(phase_id)

    def get_forbidden_techniques(self) -> list[ForbiddenTechnique]:
        """Get all forbidden techniques with reasons."""
        return list(self.spec.forbidden_techniques)

    # ── Internal ──────────────────────────────────────────────────────

    def _find_category(self, category_id: str) -> TechniqueCategory | None:
        for tc in self.spec.technique_categories:
            if tc.id == category_id:
                return tc
        return None
