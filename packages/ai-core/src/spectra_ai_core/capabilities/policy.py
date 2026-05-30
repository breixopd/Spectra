"""Server-side capability policy for high-risk assessment features."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from spectra_ai_core.agents.base import AgentContext


class Capability(StrEnum):
    CUSTOM_POC_EXECUTION = "custom_poc_execution"
    REVERSE_SHELL_LISTENER = "reverse_shell_listener"


class CapabilityVerdict(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"


@dataclass(frozen=True)
class CapabilityRequest:
    capability: Capability
    context: AgentContext
    target: str | None = None
    requires_callback: bool = False
    ttl_seconds: int | None = None


@dataclass(frozen=True)
class CapabilityDecision:
    capability: Capability
    verdict: CapabilityVerdict
    reason: str

    @property
    def allowed(self) -> bool:
        return self.verdict == CapabilityVerdict.ALLOWED


_HIGH_RISK_PHASES = {"exploitation", "post_exploitation", "verification", "poc", "manual"}
_MAX_CALLBACK_TTL_SECONDS = 3600
_ADMIN_ROLES = {"admin", "staff"}
_FEATURE_BY_CAPABILITY = {
    Capability.CUSTOM_POC_EXECUTION: "custom_poc_execution",
    Capability.REVERSE_SHELL_LISTENER: "shell_access",
}


def _deny(request: CapabilityRequest, reason: str) -> CapabilityDecision:
    return CapabilityDecision(request.capability, CapabilityVerdict.DENIED, reason)


def _allow(request: CapabilityRequest) -> CapabilityDecision:
    return CapabilityDecision(request.capability, CapabilityVerdict.ALLOWED, "capability policy satisfied")


def require_capability(request: CapabilityRequest) -> CapabilityDecision:
    """Authorize high-risk capability use from trusted server-side mission context."""
    context = request.context
    if not context.mission_id:
        return _deny(request, "mission_id is required")
    if not context.user_id:
        return _deny(request, "user_id is required")
    if not request.target:
        return _deny(request, "target is required")
    if context.target and request.target != context.target:
        return _deny(request, "requested target does not match mission context")
    role = (context.user_role or "").strip().lower()
    if role not in _ADMIN_ROLES:
        feature_name = _FEATURE_BY_CAPABILITY[request.capability]
        if context.plan_features.get(feature_name) is not True:
            return _deny(request, f"plan feature '{feature_name}' is required")
        sandbox_limit = context.tenant_quotas.get("sandbox_max_containers")
        if isinstance(sandbox_limit, int) and sandbox_limit < 1:
            return _deny(request, "tenant quota does not allow worker sandbox capacity")
    if (
        request.capability in {Capability.CUSTOM_POC_EXECUTION, Capability.REVERSE_SHELL_LISTENER}
        and context.phase not in _HIGH_RISK_PHASES
    ):
        return _deny(request, f"mission phase '{context.phase}' cannot use {request.capability.value}")
    if request.requires_callback:
        ttl = request.ttl_seconds or 900
        if ttl < 60 or ttl > _MAX_CALLBACK_TTL_SECONDS:
            return _deny(request, "callback listener TTL must be between 60 and 3600 seconds")
    return _allow(request)
