"""Tests for live framework enforcement in the tool execution path.

Covers the MAKER/framework phase-gating wired into ``ToolExecutionService`` so that
every tool run is validated against the active framework before execution.
"""

from types import SimpleNamespace

import pytest

from spectra_tools.service import ToolExecutionService


class FakeMission:
    def __init__(self, phase: str, authorized: bool = True):
        self.pentest_framework = "ptes"
        self.current_phase = phase
        self.authorization_confirmed = authorized
        self.target = "10.0.0.1"
        self.logs: list[str] = []

    def log(self, msg: str) -> None:
        self.logs.append(msg)


def _adapter(tags: list[str]):
    """A minimal stand-in for a tool adapter carrying a ToolConfig-like ``config``."""
    return SimpleNamespace(
        config=SimpleNamespace(category="custom", metadata=SimpleNamespace(capabilities=[], tags=tags))
    )


@pytest.fixture
def service() -> ToolExecutionService:
    # The enforcement helper uses no instance state, so skip __init__ (needs an LLM client).
    return ToolExecutionService.__new__(ToolExecutionService)


def test_in_phase_technique_allowed(service):
    mission = FakeMission("exploitation")
    result = service._apply_framework_enforcement(
        mission, _adapter(["exploit"]), "msf", "10.0.0.1", "msfconsole 10.0.0.1"
    )
    assert result is None


def test_unmapped_tool_allowed(service):
    mission = FakeMission("discovery")
    result = service._apply_framework_enforcement(
        mission, _adapter(["totally-unknown-tag"]), "x", "10.0.0.1", "x 10.0.0.1"
    )
    assert result is None


def test_out_of_phase_advisory_allows_but_logs(service, monkeypatch):
    from spectra_common.config import settings

    monkeypatch.setattr(settings, "FRAMEWORK_ENFORCEMENT_MODE", "advisory", raising=False)
    mission = FakeMission("discovery")  # exploitation not allowed in discovery
    result = service._apply_framework_enforcement(
        mission, _adapter(["exploit"]), "msf", "10.0.0.1", "msfconsole 10.0.0.1"
    )
    assert result is None
    assert any("FRAMEWORK-ADVISORY" in m for m in mission.logs)


def test_out_of_phase_strict_blocks(service, monkeypatch):
    from spectra_common.config import settings

    monkeypatch.setattr(settings, "FRAMEWORK_ENFORCEMENT_MODE", "strict", raising=False)
    mission = FakeMission("discovery")
    result = service._apply_framework_enforcement(
        mission, _adapter(["exploit"]), "msf", "10.0.0.1", "msfconsole 10.0.0.1"
    )
    assert result is not None
    assert result.success is False
    assert any("FRAMEWORK-BLOCK" in m for m in mission.logs)


def test_unconfirmed_authorization_always_blocks(service, monkeypatch):
    from spectra_common.config import settings

    monkeypatch.setattr(settings, "FRAMEWORK_ENFORCEMENT_MODE", "advisory", raising=False)
    mission = FakeMission("exploitation", authorized=False)  # in-phase, but auth not confirmed
    result = service._apply_framework_enforcement(
        mission, _adapter(["exploit"]), "msf", "10.0.0.1", "msfconsole 10.0.0.1"
    )
    assert result is not None
    assert result.success is False
