"""Tests for sub-agent delegation wiring across agents."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.ai.agents.base import (
    AgentContext,
    AgentResult,
    AgentRole,
)
from app.services.ai.agents.exploit_crafter import ExploitCrafter, ExploitInput
from app.services.ai.agents.mission_controller import MissionController, MissionInput
from app.services.ai.agents.post_exploitation import PostExploitationAgent, PostExploitInput
from tests.mocks.llm import MockLLMClient


def _ctx(**overrides) -> AgentContext:
    defaults = dict(mission_id="m-1", target="10.0.0.1", phase="exploitation")
    defaults.update(overrides)
    return AgentContext(**defaults)


# ---------------------------------------------------------------------------
# ExploitCrafter → POCDeveloper
# ---------------------------------------------------------------------------


class TestExploitCrafterSubAgent:
    """ExploitCrafter spawns POCDeveloper for CVE-based candidates."""

    @pytest.mark.asyncio
    async def test_spawns_poc_developer_for_cve_candidate(self):
        llm = MockLLMClient(
            structured_responses={
                "ExploitAction": {
                    "action_type": "execute_exploit",
                    "confidence": 0.85,
                    "risk_level": "high",
                    "reasoning": "CVE exploit configured",
                    "exploit_name": "cve:CVE-2021-44228",
                    "payload_type": "reverse_shell",
                    "configuration": {},
                    "attempt_number": 1,
                },
            },
        )
        agent = ExploitCrafter(llm)

        cve_candidate = {
            "name": "cve:CVE-2021-44228",
            "type": "cve_intel",
            "cve": "CVE-2021-44228",
            "description": "Log4Shell RCE",
            "confidence": 0.9,
        }

        poc_result = AgentResult(
            success=True,
            action=AsyncMock(language="python"),
            metadata={},
        )

        with (
            patch.object(agent, "_find_exploit_candidates", return_value=[cve_candidate]),
            patch.object(agent, "spawn_sub_agent", new_callable=AsyncMock, return_value=poc_result),
        ):
            input_data = ExploitInput(target="10.0.0.1", service_info={"port": 8080})
            ctx = _ctx()
            result = await agent.execute(ctx, input_data)

            assert result.success
            assert result.metadata.get("poc_generated") is True
            agent.spawn_sub_agent.assert_awaited_once()  # type: ignore[attr-defined]
            call_args = agent.spawn_sub_agent.call_args  # type: ignore[attr-defined]
            assert call_args[0][0] == AgentRole.POC_DEVELOPER

    @pytest.mark.asyncio
    async def test_no_poc_for_non_cve_candidate(self):
        llm = MockLLMClient(
            structured_responses={
                "ExploitAction": {
                    "action_type": "execute_exploit",
                    "confidence": 0.8,
                    "risk_level": "high",
                    "reasoning": "Memory-based exploit",
                    "exploit_name": "learned:nmap",
                    "payload_type": "bind_shell",
                    "configuration": {},
                    "attempt_number": 1,
                },
            },
        )
        agent = ExploitCrafter(llm)

        memory_candidate = {
            "name": "learned:nmap",
            "type": "memory",
            "confidence": 0.8,
        }

        with (
            patch.object(agent, "_find_exploit_candidates", return_value=[memory_candidate]),
            patch.object(agent, "spawn_sub_agent", new_callable=AsyncMock) as mock_spawn,
        ):
            input_data = ExploitInput(target="10.0.0.1", service_info={})
            result = await agent.execute(_ctx(), input_data)

            assert result.success
            assert "poc_generated" not in result.metadata
            mock_spawn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_poc_failure_does_not_break_exploit_result(self):
        llm = MockLLMClient(
            structured_responses={
                "ExploitAction": {
                    "action_type": "execute_exploit",
                    "confidence": 0.85,
                    "risk_level": "high",
                    "reasoning": "test",
                    "exploit_name": "cve:CVE-2023-0001",
                    "payload_type": "reverse_shell",
                    "configuration": {},
                    "attempt_number": 1,
                },
            },
        )
        agent = ExploitCrafter(llm)

        cve_candidate = {
            "name": "cve:CVE-2023-0001",
            "type": "cve_intel",
            "cve": "CVE-2023-0001",
            "description": "test vuln",
            "confidence": 0.9,
        }

        with (
            patch.object(agent, "_find_exploit_candidates", return_value=[cve_candidate]),
            patch.object(
                agent,
                "spawn_sub_agent",
                new_callable=AsyncMock,
                side_effect=RuntimeError("sub-agent crashed"),
            ),
        ):
            input_data = ExploitInput(target="10.0.0.1", service_info={"port": 443})
            result = await agent.execute(_ctx(), input_data)

            # Main result is still successful
            assert result.success
            assert "poc_generated" not in result.metadata


# ---------------------------------------------------------------------------
# PostExploitationAgent → ReconIntel
# ---------------------------------------------------------------------------


class TestPostExploitSubAgent:
    """PostExploitationAgent spawns ReconIntel for CVE enrichment."""

    @pytest.mark.asyncio
    async def test_spawns_recon_intel_for_cve_findings(self):
        llm = MockLLMClient(
            structured_responses={
                "PostExploitAction": {
                    "action_type": "post_exploit_plan",
                    "confidence": 0.8,
                    "risk_level": "medium",
                    "reasoning": "Post-exploit plan",
                    "suggested_actions": ["privesc"],
                    "persistence_methods": [],
                    "exfiltration_targets": [],
                    "tool_queue": [],
                },
            },
        )
        agent = PostExploitationAgent(llm)

        recon_result = AgentResult(
            success=True,
            action=AsyncMock(
                cve_details=[{"cve_id": "CVE-2021-44228", "cvss_score": 10.0}],
                recommendations=["Patch immediately"],
            ),
            metadata={},
        )

        ctx = _ctx(
            previous_findings=[
                {"title": "Log4Shell CVE-2021-44228", "severity": "critical"},
            ]
        )
        input_data = PostExploitInput(target="10.0.0.1", access_level="user", system_info="Linux")

        with patch.object(agent, "spawn_sub_agent", new_callable=AsyncMock, return_value=recon_result):
            result = await agent.execute(ctx, input_data)

            assert result.success
            assert result.metadata.get("cve_intel_enriched") is True
            assert result.metadata.get("cve_details_count") == 1
            agent.spawn_sub_agent.assert_awaited_once()  # type: ignore[attr-defined]
            call_args = agent.spawn_sub_agent.call_args  # type: ignore[attr-defined]
            assert call_args[0][0] == AgentRole.RECON_INTEL

    @pytest.mark.asyncio
    async def test_no_recon_intel_without_cves(self):
        llm = MockLLMClient(
            structured_responses={
                "PostExploitAction": {
                    "action_type": "post_exploit_plan",
                    "confidence": 0.8,
                    "risk_level": "low",
                    "reasoning": "basic plan",
                    "suggested_actions": [],
                    "persistence_methods": [],
                    "exfiltration_targets": [],
                    "tool_queue": [],
                },
            },
        )
        agent = PostExploitationAgent(llm)

        ctx = _ctx(previous_findings=[{"title": "Open port 80", "severity": "info"}])
        input_data = PostExploitInput(target="10.0.0.1", access_level="root", system_info="Linux")

        with patch.object(agent, "spawn_sub_agent", new_callable=AsyncMock) as mock_spawn:
            result = await agent.execute(ctx, input_data)

            assert result.success
            assert "cve_intel_enriched" not in result.metadata
            mock_spawn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_recon_intel_failure_does_not_break_result(self):
        llm = MockLLMClient(
            structured_responses={
                "PostExploitAction": {
                    "action_type": "post_exploit_plan",
                    "confidence": 0.8,
                    "risk_level": "medium",
                    "reasoning": "plan ok",
                    "suggested_actions": ["enum"],
                    "persistence_methods": [],
                    "exfiltration_targets": [],
                    "tool_queue": [],
                },
            },
        )
        agent = PostExploitationAgent(llm)

        ctx = _ctx(
            previous_findings=[
                {"title": "CVE-2023-9999 found", "severity": "high"},
            ]
        )
        input_data = PostExploitInput(target="10.0.0.1", access_level="user", system_info="Linux")

        with patch.object(
            agent,
            "spawn_sub_agent",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network error"),
        ):
            result = await agent.execute(ctx, input_data)

            assert result.success
            assert "cve_intel_enriched" not in result.metadata


# ---------------------------------------------------------------------------
# PostExploitationAgent._extract_cve_ids
# ---------------------------------------------------------------------------


class TestExtractCveIds:
    def test_extracts_cves_from_title(self):
        findings = [{"title": "Log4Shell CVE-2021-44228 RCE", "severity": "critical"}]
        assert PostExploitationAgent._extract_cve_ids(findings) == ["CVE-2021-44228"]  # type: ignore[attr-defined]

    def test_extracts_multiple_cves(self):
        findings = [
            {"title": "CVE-2021-44228", "severity": "critical"},
            {"description": "Also see CVE-2023-1234 and CVE-2023-5678"},
        ]
        ids = PostExploitationAgent._extract_cve_ids(findings)  # type: ignore[attr-defined]
        assert "CVE-2021-44228" in ids
        assert "CVE-2023-1234" in ids
        assert "CVE-2023-5678" in ids

    def test_no_duplicates(self):
        findings = [
            {"title": "CVE-2021-44228", "description": "CVE-2021-44228 again"},
        ]
        assert PostExploitationAgent._extract_cve_ids(findings) == ["CVE-2021-44228"]  # type: ignore[attr-defined]

    def test_empty_findings(self):
        assert PostExploitationAgent._extract_cve_ids([]) == []  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# MissionController → SafetyAgent
# ---------------------------------------------------------------------------


class TestMissionControllerSubAgent:
    """MissionController spawns SafetyAgent for pre-flight check."""

    @pytest.mark.asyncio
    async def test_spawns_safety_agent_preflight(self):
        llm = MockLLMClient(
            structured_responses={
                "MissionPlan": {
                    "action_type": "mission_plan",
                    "confidence": 0.85,
                    "risk_level": "low",
                    "reasoning": "Plan generated",
                    "mission_type": "full_assessment",
                    "tasks": [],
                    "current_phase": "scope",
                    "estimated_duration_minutes": 30,
                },
            },
        )

        safety_result = AgentResult(
            success=True,
            action=AsyncMock(allowed=True, risk_level="low", reason="Scope is safe"),
            metadata={},
        )

        with (
            patch("app.services.ai.consensus.VotingSystem"),
            patch.object(
                MissionController,
                "_create_mission_plan",
                new_callable=AsyncMock,
            ) as mock_plan,
            patch.object(
                MissionController,
                "spawn_sub_agent",
                new_callable=AsyncMock,
                return_value=safety_result,
            ) as mock_spawn,
        ):
            from app.services.ai.agents.mission_controller import MissionPlan

            mock_plan.return_value = MissionPlan(
                confidence=0.85,
                reasoning="Plan generated",
            )

            agent = MissionController(llm)
            ctx = _ctx(phase="scope")
            input_data = MissionInput(directive="Full security assessment")

            result = await agent.execute(ctx, input_data)

            assert result.success
            assert result.metadata.get("preflight_allowed") is True
            mock_spawn.assert_awaited_once()
            call_args = mock_spawn.call_args
            assert call_args[0][0] == AgentRole.SAFETY_SUPERVISOR

    @pytest.mark.asyncio
    async def test_safety_failure_does_not_block_mission(self):
        llm = MockLLMClient(
            structured_responses={
                "MissionPlan": {
                    "action_type": "mission_plan",
                    "confidence": 0.85,
                    "risk_level": "low",
                    "reasoning": "Plan ok",
                    "tasks": [],
                    "current_phase": "scope",
                },
            },
        )

        with (
            patch("app.services.ai.consensus.VotingSystem"),
            patch.object(
                MissionController,
                "_create_mission_plan",
                new_callable=AsyncMock,
            ) as mock_plan,
            patch.object(
                MissionController,
                "spawn_sub_agent",
                new_callable=AsyncMock,
                side_effect=RuntimeError("safety agent down"),
            ),
        ):
            from app.services.ai.agents.mission_controller import MissionPlan

            mock_plan.return_value = MissionPlan(
                confidence=0.85,
                reasoning="Plan ok",
            )

            agent = MissionController(llm)
            ctx = _ctx(phase="scope")
            input_data = MissionInput(directive="Quick recon scan")

            result = await agent.execute(ctx, input_data)

            # Mission plan still succeeds
            assert result.success
            assert "preflight_allowed" not in result.metadata
