from spectra_platform.services.ai.agents.base import AgentContext
from spectra_platform.services.security.capabilities import (
    Capability,
    CapabilityRequest,
    CapabilityVerdict,
    require_capability,
)


def _context(**overrides):
    values = {
        "mission_id": "m-1",
        "session_id": "m-1",
        "user_id": "u-1",
        "user_role": "user",
        "plan_features": {"custom_poc_execution": True, "shell_access": True},
        "tenant_quotas": {"sandbox_max_containers": 1},
        "target": "10.0.0.1",
        "phase": "exploitation",
    }
    values.update(overrides)
    return AgentContext(**values)


def test_capability_policy_allows_scoped_custom_poc():
    decision = require_capability(
        CapabilityRequest(
            capability=Capability.CUSTOM_POC_EXECUTION,
            context=_context(),
            target="10.0.0.1",
            requires_callback=True,
            ttl_seconds=900,
        )
    )

    assert decision.verdict == CapabilityVerdict.ALLOWED


def test_capability_policy_denies_target_mismatch():
    decision = require_capability(
        CapabilityRequest(
            capability=Capability.REVERSE_SHELL_LISTENER,
            context=_context(target="10.0.0.1"),
            target="10.0.0.2",
            requires_callback=True,
            ttl_seconds=900,
        )
    )

    assert decision.verdict == CapabilityVerdict.DENIED
    assert "target" in decision.reason


def test_capability_policy_denies_missing_user_context():
    decision = require_capability(
        CapabilityRequest(
            capability=Capability.CUSTOM_POC_EXECUTION,
            context=_context(user_id=None),
            target="10.0.0.1",
        )
    )

    assert decision.verdict == CapabilityVerdict.DENIED
    assert "user_id" in decision.reason


def test_capability_policy_denies_missing_plan_feature():
    decision = require_capability(
        CapabilityRequest(
            capability=Capability.CUSTOM_POC_EXECUTION,
            context=_context(plan_features={"custom_poc_execution": False, "shell_access": True}),
            target="10.0.0.1",
        )
    )

    assert decision.verdict == CapabilityVerdict.DENIED
    assert "custom_poc_execution" in decision.reason


def test_capability_policy_bounds_listener_ttl():
    decision = require_capability(
        CapabilityRequest(
            capability=Capability.REVERSE_SHELL_LISTENER,
            context=_context(),
            target="10.0.0.1",
            requires_callback=True,
            ttl_seconds=7200,
        )
    )

    assert decision.verdict == CapabilityVerdict.DENIED
    assert "TTL" in decision.reason


def test_capability_policy_denies_exhausted_worker_quota():
    decision = require_capability(
        CapabilityRequest(
            capability=Capability.CUSTOM_POC_EXECUTION,
            context=_context(tenant_quotas={"sandbox_max_containers": 0}),
            target="10.0.0.1",
        )
    )

    assert decision.verdict == CapabilityVerdict.DENIED
    assert "quota" in decision.reason
