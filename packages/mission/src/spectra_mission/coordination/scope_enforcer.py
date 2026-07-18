"""ScopeEnforcer — validates proposed pentest actions against RoE and framework policy.

Every action proposed by any agent is checked against:
1. Rules of Engagement (targets, techniques, credentials, impacts)
2. Framework constraints (phase gating, technique allowlisting, forbidden techniques)
3. Policy overlay (company-specific constraints merged at mission creation)

No action executes without passing all checks. Violations are logged and blocked.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from spectra_mission.framework_enforcer import FrameworkEnforcer
from spectra_mission.framework_loader import get_framework

logger = logging.getLogger(__name__)


@dataclass
class ScopeCheck:
    """Result of a single scope enforcement check."""

    allowed: bool
    reason: str = ""
    check_type: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class EnforcementVerdict:
    """Final verdict after all scope checks."""

    allowed: bool
    checks: list[ScopeCheck]
    blocked_by: str = ""

    @property
    def blocked_checks(self) -> list[ScopeCheck]:
        return [c for c in self.checks if not c.allowed]


class ScopeEnforcer:
    """Validates proposed pentest actions against all applicable constraints.

    Usage:
        enforcer = ScopeEnforcer(mission, framework_id="ptes")
        verdict = enforcer.validate_proposed_action("nmap -sV target.com", "port_scanning", "discovery")
        if not verdict.allowed:
            logger.warning("Action blocked: %s", verdict.blocked_by)
    """

    def __init__(self, mission: Any, framework_id: str | None = None):
        self.mission = mission
        self.framework_id = framework_id or getattr(mission, "pentest_framework", "ptes")
        self.framework_enforcer = FrameworkEnforcer(self.framework_id)
        self.framework_spec = get_framework(self.framework_id)

    # ── Main validation entry point ───────────────────────────────────

    def validate(self, action: str, technique_category: str, phase: str, /) -> EnforcementVerdict:
        """Validate a proposed action against all constraints.

        Args:
            action: The tool/command being proposed (e.g., "nmap -sV 10.0.0.1")
            technique_category: Framework technique category ID (e.g., "port_scanning")
            phase: Current assessment phase ID

        Returns:
            EnforcementVerdict with allowed status and details of all checks
        """
        checks: list[ScopeCheck] = []

        # 1. Target scope check
        checks.append(self._check_target_scope(action))

        # 2. Framework phase gating
        checks.append(self._check_framework_phase(technique_category, phase))

        # 3. Forbidden techniques check
        checks.append(self._check_forbidden_techniques(technique_category))

        # 4. Authorization check
        checks.append(self._check_authorization())

        # 5. Rate limit / quota check
        checks.append(self._check_rate_limits(technique_category))

        blocked = [c for c in checks if not c.allowed]
        return EnforcementVerdict(
            allowed=len(blocked) == 0,
            checks=checks,
            blocked_by=blocked[0].reason if blocked else "",
        )

    # ── Individual checks ─────────────────────────────────────────────

    def _check_target_scope(self, action: str) -> ScopeCheck:
        """Verify the action targets are within scope."""
        target = getattr(self.mission, "target", None)
        if not target:
            return ScopeCheck(
                allowed=False,
                check_type="target_scope",
                reason="Mission has no declared target",
            )

        action_lower = action.lower()
        scope_values = list(getattr(self.mission, "scope_targets", []) or [target])
        tokens: set[str] = set()
        for value in scope_values:
            value = str(value).strip()
            if not value:
                continue
            tokens.add(value.lower())
            parsed = urlparse(value if "://" in value else f"//{value}")
            if parsed.hostname:
                tokens.add(parsed.hostname.lower())

        if any(token and token in action_lower for token in tokens):
            return ScopeCheck(allowed=True, check_type="target_scope")

        if getattr(self.mission, "allow_indirect_targets", False):
            logger.info("Action target is indirect; explicit mission policy permits it")
            return ScopeCheck(
                allowed=True,
                check_type="target_scope",
                reason="Indirect target allowed by mission policy",
            )

        return ScopeCheck(
            allowed=False,
            check_type="target_scope",
            reason="Action does not contain a declared in-scope target",
            details={"scope_targets": scope_values},
        )

    def _check_framework_phase(self, technique: str, phase: str) -> ScopeCheck:
        """Check if the technique is allowed in the current framework phase."""
        result = self.framework_enforcer.check_technique(technique, phase)
        return ScopeCheck(
            allowed=result.allowed,
            check_type="framework_phase",
            reason=result.reason,
            details={
                "technique": technique,
                "phase": phase,
                "requires_consensus": result.requires_consensus,
                "risk_level": result.risk_level,
            },
        )

    def _check_forbidden_techniques(self, technique: str) -> ScopeCheck:
        """Check if the technique is explicitly forbidden."""
        forbidden = self.framework_spec.is_technique_forbidden(technique)
        if forbidden and forbidden.override == "none":
            return ScopeCheck(
                allowed=False,
                check_type="forbidden_technique",
                reason=f"Forbidden technique '{technique}': {forbidden.reason}",
                details={"technique": technique, "reason": forbidden.reason},
            )
        return ScopeCheck(allowed=True, check_type="forbidden_technique")

    def _check_authorization(self) -> ScopeCheck:
        """Verify authorization is confirmed for this mission."""
        auth = getattr(self.mission, "authorization_confirmed", None)
        if auth is not True:
            return ScopeCheck(
                allowed=False,
                check_type="authorization",
                reason="Mission authorization not confirmed",
            )
        return ScopeCheck(allowed=True, check_type="authorization")

    def _check_rate_limits(self, technique: str) -> ScopeCheck:
        """Check rate limits and attempt counts."""
        # Delegate to framework constraints via the enforcer
        # This will be expanded when we track per-technique attempt counts
        return ScopeCheck(allowed=True, check_type="rate_limits")
